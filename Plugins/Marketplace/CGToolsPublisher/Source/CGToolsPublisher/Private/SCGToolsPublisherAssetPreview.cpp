#include "SCGToolsPublisherAssetPreview.h"

#include "Engine/Texture2D.h"
#include "Misc/ObjectThumbnail.h"
#include "ObjectTools.h"
#include "Slate/DeferredCleanupSlateBrush.h"
#include "Styling/AppStyle.h"
#include "Styling/SlateIconFinder.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SScaleBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/Text/STextBlock.h"

void SCGToolsPublisherAssetPreview::Construct(const FArguments& InArgs)
{
    ClassThumbnail = FSlateIconFinder::FindCustomIconBrushForClass(
        InArgs._AssetData.GetClass(), TEXT("ClassThumbnail"));
    FObjectThumbnail Thumbnail;
    const auto HasVisiblePixels = [&Thumbnail]()
    {
        const TArray<uint8>& Bytes = Thumbnail.GetUncompressedImageData();
        if (Thumbnail.GetImageWidth() <= 0 || Thumbnail.GetImageHeight() <= 0
            || Bytes.Num() != Thumbnail.GetImageWidth() * Thumbnail.GetImageHeight() * 4)
        {
            return false;
        }
        for (int32 Index = 0; Index < Bytes.Num(); Index += 4)
        {
            if (Bytes[Index] > 4 || Bytes[Index + 1] > 4 || Bytes[Index + 2] > 4)
            {
                return true;
            }
        }
        return false;
    };
    if (!ThumbnailTools::LoadThumbnailFromPackage(InArgs._AssetData, Thumbnail) || !HasVisiblePixels())
    {
        if (UObject* Asset = InArgs._AssetData.GetAsset())
        {
            ThumbnailTools::RenderThumbnail(Asset, 256, 256,
                ThumbnailTools::EThumbnailTextureFlushMode::AlwaysFlush, nullptr, &Thumbnail);
        }
    }
    if (HasVisiblePixels())
    {
        TArray<uint8> Pixels = Thumbnail.GetUncompressedImageData();
        for (int32 Index = 3; Index < Pixels.Num(); Index += 4)
        {
            Pixels[Index] = 255;
        }
        const FName Name(*FString::Printf(TEXT("CGToolsPublisher_Preview_%s"),
            *FGuid::NewGuid().ToString(EGuidFormats::Digits)));
        UTexture2D* Texture = UTexture2D::CreateTransient(Thumbnail.GetImageWidth(), Thumbnail.GetImageHeight(),
            PF_B8G8R8A8, Name, TConstArrayView64<uint8>(Pixels.GetData(), Pixels.Num()));
        if (Texture)
        {
            Texture->SRGB = true;
            Texture->Filter = TF_Bilinear;
            Texture->LODGroup = TEXTUREGROUP_UI;
            Texture->NeverStream = true;
            Texture->UpdateResource();
            PreviewBrush = FDeferredCleanupSlateBrush::CreateBrush(Texture,
                FVector2D(Thumbnail.GetImageWidth(), Thumbnail.GetImageHeight()));
        }
    }
    ChildSlot
    [
        SNew(SBox).WidthOverride(256.0f)
        [
            SNew(SVerticalBox)
            + SVerticalBox::Slot().AutoHeight()
            [
                SNew(SBox).WidthOverride(256.0f).HeightOverride(256.0f)
                [
                    SNew(SBorder).BorderImage(FAppStyle::GetBrush("Brushes.Recessed")).Padding(0)
                    [
                        SNew(SScaleBox).Stretch(EStretch::ScaleToFit)
                        [ SNew(SImage).Image(PreviewBrush.IsValid() ? PreviewBrush->GetSlateBrush() : ClassThumbnail) ]
                    ]
                ]
            ]
            + SVerticalBox::Slot().AutoHeight().Padding(0, 10, 0, 0)
            [
                SNew(STextBlock).Text(FText::FromName(InArgs._AssetData.AssetName))
                .Font(FAppStyle::GetFontStyle("HeadingExtraSmall"))
                .Justification(ETextJustify::Center).AutoWrapText(true)
            ]
            + SVerticalBox::Slot().AutoHeight().Padding(0, 6, 0, 0)
            [
                SNew(STextBlock).Text(FText::FromName(InArgs._AssetData.PackageName))
                .ToolTipText(FText::FromName(InArgs._AssetData.PackageName))
                .ColorAndOpacity(FSlateColor::UseSubduedForeground())
                .Justification(ETextJustify::Center).AutoWrapText(true)
            ]
        ]
    ];
}
