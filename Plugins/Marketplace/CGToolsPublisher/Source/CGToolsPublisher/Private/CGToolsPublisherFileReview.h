#pragma once

#include "CoreMinimal.h"
#include "Misc/SecureHash.h"

class SWindow;

namespace CGToolsPublisher
{
    enum class EPublishFileDifference : uint8 { Conflict, Added, Missing, Identical };

    struct FPublishFile
    {
        FString Relative;
        FString Source;
        FString Target;
        int64 SourceSize = -1;
        int64 TargetSize = -1;
        FMD5Hash SourceHash;
        FMD5Hash TargetHash;
        EPublishFileDifference Difference = EPublishFileDifference::Identical;
        bool bSelected = false;
        bool CanSelect() const { return Difference == EPublishFileDifference::Conflict || Difference == EPublishFileDifference::Added; }
    };

    struct FPublishFilePlan
    {
        TArray<TSharedPtr<FPublishFile>> Files;
        FString Error;
        int32 NumSelectable() const;
        int32 NumSelected() const;
        void Select(const TSharedPtr<FPublishFile>& File, bool bSelected);
        void SelectAll(bool bSelected);
    };

    struct FPublishFileResult
    {
        bool bSucceeded = false;
        bool bComplete = false;
        int32 Copied = 0;
        int32 Skipped = 0;
        FString History;
        FString Error;
    };

    // Roots are relative files/directories belonging to this publish, never history.
    // Missing files exist only on the server and are always retained.
    FPublishFilePlan BuildPublishFilePlan(const FString& Stage, const FString& Target, const TArray<FString>& Roots);
    FPublishFilePlan PreparePublishFilePlan(const FString& Stage, const FString& Target, const TArray<FString>& Roots);
    bool ReviewPublishFiles(const TSharedRef<FPublishFilePlan>& Plan, const FString& Label, const TSharedPtr<SWindow>& Parent);
    FPublishFileResult CommitPublishFiles(const FPublishFilePlan& Plan, const FString& BackupBase);
    bool ReviewAndCommitPublishFiles(const FString& Stage, const FString& Target, const TArray<FString>& Roots,
        const FString& BackupBase, const FString& Label, const TSharedPtr<SWindow>& Parent, FPublishFileResult& OutResult);
}
