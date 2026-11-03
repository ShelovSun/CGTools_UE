// Copyright CGTools. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "MayaBridgeTypes.h"

class FMayaBridgeProtocol
{
public:
    static constexpr uint32 MaxJsonBodyBytes = 1024U * 1024U;

    static bool ParseMessage(
        const TArray<uint8>& JsonBytes,
        FMayaBridgeMessage& OutMessage,
        FString& OutError);

    static TArray<uint8> MakeAckFrame(
        const FString& EventId,
        bool bAccepted,
        const FString& Message);
};
