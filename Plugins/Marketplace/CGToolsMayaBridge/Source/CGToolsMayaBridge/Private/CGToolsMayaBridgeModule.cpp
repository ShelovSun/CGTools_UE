// Copyright CGTools. All Rights Reserved.

#include "CGToolsMayaBridgeModule.h"

#include "CGToolsMayaBridgeLog.h"
#include "MayaActionImporter.h"
#include "MayaBridgeServer.h"
#include "MayaBridgeSettings.h"

DEFINE_LOG_CATEGORY(LogCGToolsMayaBridge);

void FCGToolsMayaBridgeModule::StartupModule()
{
    if (IsRunningCommandlet())
    {
        return;
    }

    const FMayaBridgeSettings Settings = FMayaBridgeSettingsLoader::Load();
    Importer = MakeShared<FMayaActionImporter, ESPMode::ThreadSafe>(Settings);

    // UE 5.7 Interchange performs a synchronous wait which pumps Game Thread
    // tasks. Calling it from an AsyncTask(GameThread) callback trips the
    // TaskGraph recursion guard, so messages are consumed from the regular
    // Editor ticker instead.
    TickerHandle = FTSTicker::GetCoreTicker().AddTicker(
        TEXT("CGToolsMayaBridge"),
        0.0f,
        [this](float DeltaTime)
        {
            return Tick(DeltaTime);
        });

    Server = MakeUnique<FMayaBridgeServer>(
        Settings,
        [this](FMayaBridgeMessage Message)
        {
            PendingMessages.Enqueue(MoveTemp(Message));
        });

    if (!Server->Start())
    {
        Server.Reset();
    }
}

void FCGToolsMayaBridgeModule::ShutdownModule()
{
    FMayaActionImporter::CancelPendingFocus();
    if (Server.IsValid())
    {
        Server->Shutdown();
        Server.Reset();
    }

    if (TickerHandle.IsValid())
    {
        FTSTicker::RemoveTicker(TickerHandle);
        TickerHandle.Reset();
    }

    FMayaBridgeMessage DiscardedMessage;
    while (PendingMessages.Dequeue(DiscardedMessage))
    {
    }
    Importer.Reset();
}

bool FCGToolsMayaBridgeModule::Tick(float DeltaTime)
{
    check(IsInGameThread());

    if (bImportInProgress)
    {
        return true;
    }

    FMayaBridgeMessage Message;
    if (PendingMessages.Dequeue(Message) && Importer.IsValid())
    {
        TGuardValue<bool> ImportGuard(bImportInProgress, true);
        Importer->PromptAndImport(Message);
    }

    return true;
}

IMPLEMENT_MODULE(FCGToolsMayaBridgeModule, CGToolsMayaBridge)
