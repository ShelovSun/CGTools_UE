#include "CGToolsPublisherLibrary.h"
#include "CGToolsPublisherScreenshot.h"

#include "Framework/Application/SlateApplication.h"
#include "HAL/FileManager.h"
#include "ImageUtils.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

void UCGToolsPublisherLibrary::CaptureScreenshotToFile(
    const FString& OutputFilename, bool& bOutAccepted, FString& OutError)
{
    bOutAccepted = false;
    OutError.Reset();
    if (!IsInGameThread() || !FSlateApplication::IsInitialized())
    {
        OutError = TEXT("截图需要在 UE 编辑器主线程中执行。");
        return;
    }
    if (OutputFilename.IsEmpty() || FPaths::IsRelative(OutputFilename)
        || !FPaths::GetExtension(OutputFilename).Equals(TEXT("png"), ESearchCase::IgnoreCase))
    {
        OutError = TEXT("截图临时文件必须使用绝对路径，扩展名为 .png。");
        return;
    }
    if (!IFileManager::Get().DirectoryExists(*FPaths::GetPath(OutputFilename)))
    {
        OutError = FString::Printf(TEXT("截图临时目录不存在：%s"), *FPaths::GetPath(OutputFilename));
        return;
    }

    TArray<FColor> Pixels;
    FIntPoint Size;
    FText CaptureError;
    if (!CGToolsPublisher::CaptureScreenshotPixels(
            Pixels, Size, FSlateApplication::Get().GetActiveTopLevelWindow(), CaptureError))
    {
        OutError = CaptureError.ToString();
        return;
    }
    TArray64<uint8> Png;
    FImageUtils::PNGCompressImageArray(
        Size.X, Size.Y,
        TArrayView64<const FColor>(Pixels.GetData(), static_cast<int64>(Pixels.Num())), Png);
    if (Png.IsEmpty() || !FFileHelper::SaveArrayToFile(Png, *OutputFilename))
    {
        OutError = FString::Printf(TEXT("截图临时文件保存失败：%s"), *OutputFilename);
        return;
    }
    bOutAccepted = true;
}
