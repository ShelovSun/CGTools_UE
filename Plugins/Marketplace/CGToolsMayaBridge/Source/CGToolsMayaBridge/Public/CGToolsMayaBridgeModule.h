// Copyright CGTools. All Rights Reserved.

#pragma once

#include "Containers/Queue.h"
#include "Containers/Ticker.h"
#include "MayaBridgeTypes.h"
#include "Modules/ModuleManager.h"

class FMayaActionImporter;
class FMayaBridgeServer;

class FCGToolsMayaBridgeModule final : public IModuleInterface
{
public:
    virtual void StartupModule() override;
    virtual void ShutdownModule() override;

private:
    bool Tick(float DeltaTime);

    TSharedPtr<FMayaActionImporter, ESPMode::ThreadSafe> Importer;
    TUniquePtr<FMayaBridgeServer> Server;
    TQueue<FMayaBridgeMessage, EQueueMode::Mpsc> PendingMessages;
    FTSTicker::FDelegateHandle TickerHandle;
    bool bImportInProgress = false;
};
