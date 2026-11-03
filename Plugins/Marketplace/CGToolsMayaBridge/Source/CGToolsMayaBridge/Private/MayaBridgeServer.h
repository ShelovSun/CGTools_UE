// Copyright CGTools. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "HAL/Runnable.h"
#include "HAL/ThreadSafeBool.h"
#include "MayaBridgeTypes.h"

class FSocket;
class FRunnableThread;
class ISocketSubsystem;

class FMayaBridgeServer final : public FRunnable
{
public:
    using FMessageHandler = TFunction<void(FMayaBridgeMessage)>;

    FMayaBridgeServer(const FMayaBridgeSettings& InSettings, FMessageHandler InMessageHandler);
    virtual ~FMayaBridgeServer() override;

    bool Start();
    void Shutdown();

    virtual uint32 Run() override;
    virtual void Stop() override;

private:
    bool ReceiveOneMessage(FSocket* ClientSocket, TArray<uint8>& OutPayload, FString& OutError) const;
    bool ReceiveExact(FSocket* Socket, uint8* Destination, int32 ByteCount) const;
    bool SendAll(FSocket* Socket, const TArray<uint8>& Data) const;
    void HandleClient(FSocket* ClientSocket);
    bool RememberEvent(const FString& EventId);
    void CloseSockets();

    FMayaBridgeSettings Settings;
    FMessageHandler MessageHandler;
    FThreadSafeBool bStopping = false;
    FRunnableThread* Thread = nullptr;
    ISocketSubsystem* SocketSubsystem = nullptr;
    FSocket* ListenerSocket = nullptr;
    FSocket* CurrentClientSocket = nullptr;
    mutable FCriticalSection SocketMutex;
    TSet<FString> SeenEventIds;
    TArray<FString> SeenEventOrder;
};
