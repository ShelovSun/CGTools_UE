// Copyright CGTools. All Rights Reserved.

#include "MayaBridgeServer.h"

#include "CGToolsMayaBridgeLog.h"
#include "HAL/RunnableThread.h"
#include "IPAddress.h"
#include "MayaBridgeProtocol.h"
#include "SocketSubsystem.h"
#include "Sockets.h"

namespace
{
constexpr int32 MaximumRememberedEvents = 2048;
}

FMayaBridgeServer::FMayaBridgeServer(
    const FMayaBridgeSettings& InSettings,
    FMessageHandler InMessageHandler)
    : Settings(InSettings)
    , MessageHandler(MoveTemp(InMessageHandler))
{
}

FMayaBridgeServer::~FMayaBridgeServer()
{
    Shutdown();
}

bool FMayaBridgeServer::Start()
{
    if (Thread != nullptr)
    {
        return true;
    }

    bStopping = false;
    SocketSubsystem = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM);
    if (SocketSubsystem == nullptr)
    {
        UE_LOG(LogCGToolsMayaBridge, Error, TEXT("The platform socket subsystem is unavailable."));
        return false;
    }

    ListenerSocket = SocketSubsystem->CreateSocket(
        NAME_Stream,
        TEXT("CGTools Maya Bridge Listener"),
        false);
    if (ListenerSocket == nullptr)
    {
        UE_LOG(LogCGToolsMayaBridge, Error, TEXT("Could not create the Maya bridge listener socket."));
        return false;
    }

    TSharedRef<FInternetAddr> LoopbackAddress = SocketSubsystem->CreateInternetAddr();
    bool bAddressIsValid = false;
    LoopbackAddress->SetIp(TEXT("127.0.0.1"), bAddressIsValid);
    LoopbackAddress->SetPort(Settings.Port);

    ListenerSocket->SetReuseAddr(true);
    ListenerSocket->SetLinger(false, 0);
    if (!bAddressIsValid
        || !ListenerSocket->Bind(*LoopbackAddress)
        || !ListenerSocket->Listen(8))
    {
        const ESocketErrors SocketError = SocketSubsystem->GetLastErrorCode();
        UE_LOG(
            LogCGToolsMayaBridge,
            Error,
            TEXT("Could not listen on 127.0.0.1:%d (%s). This Unreal instance will continue without the Maya bridge."),
            Settings.Port,
            SocketSubsystem->GetSocketError(SocketError));
        CloseSockets();
        return false;
    }

    Thread = FRunnableThread::Create(
        this,
        TEXT("CGToolsMayaBridgeServer"),
        0,
        TPri_Normal);
    if (Thread == nullptr)
    {
        UE_LOG(LogCGToolsMayaBridge, Error, TEXT("Could not create the Maya bridge worker thread."));
        CloseSockets();
        return false;
    }

    UE_LOG(
        LogCGToolsMayaBridge,
        Log,
        TEXT("Listening for all Maya action publishes on 127.0.0.1:%d. This is the first active Unreal bridge instance."),
        Settings.Port);
    return true;
}

void FMayaBridgeServer::Shutdown()
{
    Stop();
    if (Thread != nullptr)
    {
        Thread->WaitForCompletion();
        delete Thread;
        Thread = nullptr;
    }
    CloseSockets();
}

uint32 FMayaBridgeServer::Run()
{
    while (!bStopping)
    {
        FSocket* LocalListener = nullptr;
        {
            FScopeLock Lock(&SocketMutex);
            LocalListener = ListenerSocket;
        }
        if (LocalListener == nullptr)
        {
            break;
        }

        bool bHasPendingConnection = false;
        const bool bWaitSucceeded = LocalListener->WaitForPendingConnection(
            bHasPendingConnection,
            FTimespan::FromMilliseconds(250));
        if (bStopping)
        {
            break;
        }
        if (!bWaitSucceeded || !bHasPendingConnection)
        {
            continue;
        }

        FSocket* ClientSocket = LocalListener->Accept(TEXT("CGTools Maya Bridge Client"));
        if (ClientSocket == nullptr)
        {
            continue;
        }
        ClientSocket->SetNoDelay(true);
        ClientSocket->SetLinger(false, 0);

        {
            FScopeLock Lock(&SocketMutex);
            CurrentClientSocket = ClientSocket;
        }

        HandleClient(ClientSocket);

        {
            FScopeLock Lock(&SocketMutex);
            if (CurrentClientSocket == ClientSocket)
            {
                CurrentClientSocket = nullptr;
            }
        }
        ClientSocket->Close();
        SocketSubsystem->DestroySocket(ClientSocket);
    }

    return 0;
}

void FMayaBridgeServer::Stop()
{
    bStopping = true;
    FScopeLock Lock(&SocketMutex);
    if (CurrentClientSocket != nullptr)
    {
        CurrentClientSocket->Close();
    }
    if (ListenerSocket != nullptr)
    {
        ListenerSocket->Close();
    }
}

bool FMayaBridgeServer::ReceiveOneMessage(
    FSocket* ClientSocket,
    TArray<uint8>& OutPayload,
    FString& OutError) const
{
    uint8 Header[4] = {0, 0, 0, 0};
    if (!ReceiveExact(ClientSocket, Header, UE_ARRAY_COUNT(Header)))
    {
        OutError = TEXT("connection closed before the complete frame header was received");
        return false;
    }

    const uint32 BodyLength =
        (static_cast<uint32>(Header[0]) << 24)
        | (static_cast<uint32>(Header[1]) << 16)
        | (static_cast<uint32>(Header[2]) << 8)
        | static_cast<uint32>(Header[3]);

    if (BodyLength == 0 || BodyLength > FMayaBridgeProtocol::MaxJsonBodyBytes)
    {
        OutError = FString::Printf(TEXT("invalid JSON body length: %u"), BodyLength);
        return false;
    }

    OutPayload.SetNumUninitialized(static_cast<int32>(BodyLength));
    if (!ReceiveExact(ClientSocket, OutPayload.GetData(), OutPayload.Num()))
    {
        OutError = TEXT("connection closed before the complete JSON body was received");
        OutPayload.Reset();
        return false;
    }

    return true;
}

bool FMayaBridgeServer::ReceiveExact(
    FSocket* Socket,
    uint8* Destination,
    const int32 ByteCount) const
{
    int32 TotalBytesRead = 0;
    while (TotalBytesRead < ByteCount && !bStopping)
    {
        if (!Socket->Wait(ESocketWaitConditions::WaitForRead, FTimespan::FromMilliseconds(100)))
        {
            if (Socket->GetConnectionState() != SCS_Connected)
            {
                return false;
            }
            continue;
        }

        int32 BytesRead = 0;
        if (!Socket->Recv(
                Destination + TotalBytesRead,
                ByteCount - TotalBytesRead,
                BytesRead,
                ESocketReceiveFlags::None)
            || BytesRead <= 0)
        {
            return false;
        }
        TotalBytesRead += BytesRead;
    }

    return TotalBytesRead == ByteCount;
}

bool FMayaBridgeServer::SendAll(FSocket* Socket, const TArray<uint8>& Data) const
{
    int32 TotalBytesSent = 0;
    while (TotalBytesSent < Data.Num() && !bStopping)
    {
        if (!Socket->Wait(ESocketWaitConditions::WaitForWrite, FTimespan::FromMilliseconds(100)))
        {
            if (Socket->GetConnectionState() != SCS_Connected)
            {
                return false;
            }
            continue;
        }

        int32 BytesSent = 0;
        if (!Socket->Send(Data.GetData() + TotalBytesSent, Data.Num() - TotalBytesSent, BytesSent)
            || BytesSent <= 0)
        {
            return false;
        }
        TotalBytesSent += BytesSent;
    }

    return TotalBytesSent == Data.Num();
}

void FMayaBridgeServer::HandleClient(FSocket* ClientSocket)
{
    TArray<uint8> Payload;
    FString ReceiveError;
    if (!ReceiveOneMessage(ClientSocket, Payload, ReceiveError))
    {
        if (!bStopping)
        {
            UE_LOG(LogCGToolsMayaBridge, Warning, TEXT("Rejected incomplete Maya bridge frame: %s"), *ReceiveError);
        }
        return;
    }

    FMayaBridgeMessage Message;
    FString ValidationError;
    bool bAccepted = FMayaBridgeProtocol::ParseMessage(Payload, Message, ValidationError);
    const FString ReplyEventId = Message.EventId;
    FString AckMessage;

    if (!bAccepted)
    {
        AckMessage = ValidationError;
    }
    else if (!RememberEvent(Message.EventId))
    {
        AckMessage = TEXT("duplicate ignored");
    }
    else if (!MessageHandler)
    {
        bAccepted = false;
        AckMessage = TEXT("bridge message handler is unavailable");
    }
    else
    {
        const FString EventId = Message.EventId;
        MessageHandler(MoveTemp(Message));
        AckMessage = TEXT("queued");
        UE_LOG(LogCGToolsMayaBridge, Log, TEXT("Queued Maya publish event %s."), *EventId);
    }

    const TArray<uint8> AckFrame = FMayaBridgeProtocol::MakeAckFrame(
        ReplyEventId,
        bAccepted,
        AckMessage);
    if (!SendAll(ClientSocket, AckFrame) && !bStopping)
    {
        UE_LOG(LogCGToolsMayaBridge, Warning, TEXT("Could not send Maya bridge ACK."));
    }
    else if (!bAccepted)
    {
        UE_LOG(LogCGToolsMayaBridge, Warning, TEXT("Rejected Maya publish event: %s"), *AckMessage);
    }
}

bool FMayaBridgeServer::RememberEvent(const FString& EventId)
{
    if (SeenEventIds.Contains(EventId))
    {
        return false;
    }

    SeenEventIds.Add(EventId);
    SeenEventOrder.Add(EventId);
    if (SeenEventOrder.Num() > MaximumRememberedEvents)
    {
        SeenEventIds.Remove(SeenEventOrder[0]);
        SeenEventOrder.RemoveAt(0, 1, EAllowShrinking::No);
    }
    return true;
}

void FMayaBridgeServer::CloseSockets()
{
    if (SocketSubsystem == nullptr)
    {
        return;
    }

    FScopeLock Lock(&SocketMutex);
    if (CurrentClientSocket != nullptr)
    {
        CurrentClientSocket->Close();
        SocketSubsystem->DestroySocket(CurrentClientSocket);
        CurrentClientSocket = nullptr;
    }
    if (ListenerSocket != nullptr)
    {
        ListenerSocket->Close();
        SocketSubsystem->DestroySocket(ListenerSocket);
        ListenerSocket = nullptr;
    }
}
