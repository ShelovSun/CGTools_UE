#pragma once

#include "CoreMinimal.h"

class FJsonObject;

struct FCGToolsDatabaseResult
{
    bool bOk = false;
    bool bExists = false;
    FString Error;
};

class FCGToolsPublisherDatabase
{
public:
    static FCGToolsDatabaseResult CheckSceneRecord(
        const FString& Project,
        const FString& AssetName,
        const FString& Host
    );

    static FCGToolsDatabaseResult CheckAssetRecord(
        const FString& Project,
        const FString& AssetName,
        const FString& Host
    );

    static FCGToolsDatabaseResult WriteSceneRecord(
        const FString& Project,
        const FString& AssetName,
        const FString& ChineseName,
        const FString& AssetType,
        const FString& IconPath,
        const FString& Host,
        bool bOverwrite
    );

    static FCGToolsDatabaseResult WriteAssetRecord(
        const FString& Project,
        const FString& AssetName,
        const FString& ChineseName,
        const FString& AssetType,
        const FString& IconPath,
        const FString& Host,
        bool bOverwrite
    );

private:
    static FCGToolsDatabaseResult Invoke(
        const FString& Operation,
        const TSharedRef<FJsonObject>& Payload
    );
};
