#include "SCGToolsPublisherWindow.h"
#include "CGToolsPublisherAssetUtils.h"
#include "CGToolsPublisherAssetFolder.h"
#include "CGToolsPublisherMeshExport.h"
#include "CGToolsPublisherScreenshot.h"

#include "Async/Async.h"
#include "AssetExportTask.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "AssetThumbnail.h"
#include "AssetToolsModule.h"
#include "CGToolsPublisherDatabase.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "DesktopPlatformModule.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "Engine/Texture.h"
#include "Engine/Texture2D.h"
#include "Exporters/Exporter.h"
#include "Exporters/TextureExporterEXR.h"
#include "Exporters/TextureExporterPNG.h"
#include "Framework/Application/SlateApplication.h"
#include "GenericPlatform/GenericApplication.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformFile.h"
#include "HAL/PlatformFileManager.h"
#include "HAL/PlatformProcess.h"
#include "IAssetTools.h"
#include "ImageUtils.h"
#include "IDesktopPlatform.h"
#include "Input/CursorReply.h"
#include "InputCoreTypes.h"
#include "Misc/ConfigCacheIni.h"
#include "Misc/DateTime.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "Misc/Guid.h"
#include "Misc/MessageDialog.h"
#include "Misc/ObjectThumbnail.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Misc/ScopedSlowTask.h"
#include "Modules/ModuleManager.h"
#include "ObjectTools.h"
#include "Rendering/DrawElements.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Slate/DeferredCleanupSlateBrush.h"
#include "Styling/AppStyle.h"
#include "Styling/CoreStyle.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Images/SThrobber.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Input/SEditableText.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SConstraintCanvas.h"
#include "Widgets/Layout/SGridPanel.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Layout/SScaleBox.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/Layout/SSplitter.h"
#include "Widgets/SLeafWidget.h"
#include "Widgets/SNullWidget.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/Notifications/SProgressBar.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SWindow.h"
#include "Widgets/Text/STextBlock.h"
#include "UObject/StructOnScope.h"
#include "UObject/UObjectGlobals.h"
#include "UObject/UnrealType.h"

#if PLATFORM_WINDOWS
#include "Windows/WindowsHWrapper.h"
#endif

#define LOCTEXT_NAMESPACE "CGToolsPublisherWindow"

DEFINE_LOG_CATEGORY_STATIC(LogCGToolsPublisher, Log, All);

namespace
{
    constexpr const TCHAR* CommonSettingPath =
        TEXT("Y:/MCCTools/config/ShotManager_config/commonSetting.json");

    TSharedPtr<FDeferredCleanupSlateBrush> CreatePreviewBrush(
        const TArray<FColor>& Pixels,
        const FIntPoint Size,
        const TCHAR* DebugPrefix
    )
    {
        if (Size.X <= 0
            || Size.Y <= 0
            || Pixels.Num() != Size.X * Size.Y)
        {
            return nullptr;
        }

        const FName TextureName(*FString::Printf(
            TEXT("%s_%s"),
            DebugPrefix,
            *FGuid::NewGuid().ToString(EGuidFormats::Digits)
        ));
        const TConstArrayView64<uint8> ImageBytes(
            reinterpret_cast<const uint8*>(Pixels.GetData()),
            static_cast<int64>(Pixels.Num()) * sizeof(FColor)
        );
        UTexture2D* Texture = UTexture2D::CreateTransient(
            Size.X,
            Size.Y,
            PF_B8G8R8A8,
            TextureName,
            ImageBytes
        );
        if (!Texture)
        {
            return nullptr;
        }

        Texture->SRGB = true;
        Texture->Filter = TF_Bilinear;
        Texture->LODGroup = TEXTUREGROUP_UI;
        Texture->NeverStream = true;
        Texture->UpdateResource();

        return FDeferredCleanupSlateBrush::CreateBrush(
            Texture,
            FVector2D(Size.X, Size.Y)
        );
    }

    bool CaptureVirtualDesktopPixels(
        TArray<FColor>& OutPixels,
        FIntPoint& OutSize,
        FIntPoint& OutDesktopOrigin
    )
    {
        OutPixels.Reset();
        OutSize = FIntPoint::ZeroValue;
        OutDesktopOrigin = FIntPoint::ZeroValue;

#if PLATFORM_WINDOWS
        FDisplayMetrics DisplayMetrics;
        FDisplayMetrics::RebuildDisplayMetrics(DisplayMetrics);
        const FPlatformRect& VirtualRect = DisplayMetrics.VirtualDisplayRect;
        const int32 Width = VirtualRect.Right - VirtualRect.Left;
        const int32 Height = VirtualRect.Bottom - VirtualRect.Top;
        const int64 PixelCount = static_cast<int64>(Width) * Height;
        if (Width <= 0
            || Height <= 0
            || PixelCount <= 0
            || PixelCount > MAX_int32)
        {
            return false;
        }

        HDC ScreenDC = ::GetDC(nullptr);
        if (!ScreenDC)
        {
            return false;
        }

        HDC CaptureDC = ::CreateCompatibleDC(ScreenDC);
        if (!CaptureDC)
        {
            ::ReleaseDC(nullptr, ScreenDC);
            return false;
        }

        BITMAPINFO BitmapInfo = {};
        BitmapInfo.bmiHeader.biSize = sizeof(BitmapInfo.bmiHeader);
        BitmapInfo.bmiHeader.biWidth = Width;
        BitmapInfo.bmiHeader.biHeight = -Height;
        BitmapInfo.bmiHeader.biPlanes = 1;
        BitmapInfo.bmiHeader.biBitCount = 32;
        BitmapInfo.bmiHeader.biCompression = 0;

        void* BitmapPixels = nullptr;
        HBITMAP CaptureBitmap = ::CreateDIBSection(
            ScreenDC,
            &BitmapInfo,
            0,
            &BitmapPixels,
            nullptr,
            0
        );
        if (!CaptureBitmap || !BitmapPixels)
        {
            if (CaptureBitmap)
            {
                ::DeleteObject(CaptureBitmap);
            }
            ::DeleteDC(CaptureDC);
            ::ReleaseDC(nullptr, ScreenDC);
            return false;
        }

        HGDIOBJ PreviousBitmap = ::SelectObject(CaptureDC, CaptureBitmap);
        constexpr uint32 CopyAndCaptureLayeredWindows = 0x00CC0020u | 0x40000000u;
        const bool bCopied = PreviousBitmap != nullptr
            && ::BitBlt(
                CaptureDC,
                0,
                0,
                Width,
                Height,
                ScreenDC,
                VirtualRect.Left,
                VirtualRect.Top,
                CopyAndCaptureLayeredWindows
            ) != 0;

        if (bCopied)
        {
            OutPixels.SetNumUninitialized(static_cast<int32>(PixelCount));
            FMemory::Memcpy(
                OutPixels.GetData(),
                BitmapPixels,
                static_cast<SIZE_T>(Width) * Height * sizeof(FColor)
            );
            OutSize = FIntPoint(Width, Height);
            OutDesktopOrigin = FIntPoint(VirtualRect.Left, VirtualRect.Top);
        }

        if (PreviousBitmap)
        {
            ::SelectObject(CaptureDC, PreviousBitmap);
        }
        ::DeleteObject(CaptureBitmap);
        ::DeleteDC(CaptureDC);
        ::ReleaseDC(nullptr, ScreenDC);
        return bCopied;
#else
        return false;
#endif
    }

    bool CopyPixelsToClipboard(
        const TArray<FColor>& Pixels,
        const FIntPoint Size,
        void* OwnerWindowHandle
    )
    {
#if PLATFORM_WINDOWS
        if (Size.X <= 0
            || Size.Y <= 0
            || Pixels.Num() != Size.X * Size.Y)
        {
            return false;
        }

        HDC ScreenDC = ::GetDC(nullptr);
        if (!ScreenDC)
        {
            return false;
        }

        BITMAPINFO BitmapInfo = {};
        BitmapInfo.bmiHeader.biSize = sizeof(BitmapInfo.bmiHeader);
        BitmapInfo.bmiHeader.biWidth = Size.X;
        BitmapInfo.bmiHeader.biHeight = -Size.Y;
        BitmapInfo.bmiHeader.biPlanes = 1;
        BitmapInfo.bmiHeader.biBitCount = 32;
        BitmapInfo.bmiHeader.biCompression = 0;

        void* BitmapPixels = nullptr;
        HBITMAP ClipboardBitmap = ::CreateDIBSection(
            ScreenDC,
            &BitmapInfo,
            0,
            &BitmapPixels,
            nullptr,
            0
        );
        if (!ClipboardBitmap || !BitmapPixels)
        {
            if (ClipboardBitmap)
            {
                ::DeleteObject(ClipboardBitmap);
            }
            ::ReleaseDC(nullptr, ScreenDC);
            return false;
        }

        FMemory::Memcpy(
            BitmapPixels,
            Pixels.GetData(),
            static_cast<SIZE_T>(Pixels.Num()) * sizeof(FColor)
        );
        ::GdiFlush();

        bool bCopied = false;
        if (::OpenClipboard(static_cast<HWND>(OwnerWindowHandle)))
        {
            if (::EmptyClipboard()
                && ::SetClipboardData(CF_BITMAP, ClipboardBitmap) != nullptr)
            {
                // Windows owns the HBITMAP after SetClipboardData succeeds.
                ClipboardBitmap = nullptr;
                bCopied = true;
            }
            ::CloseClipboard();
        }

        if (ClipboardBitmap)
        {
            ::DeleteObject(ClipboardBitmap);
        }
        ::ReleaseDC(nullptr, ScreenDC);
        return bCopied;
#else
        return false;
#endif
    }

    class SCGToolsScreenshotOverlay : public SCompoundWidget
    {
    public:
        SLATE_BEGIN_ARGS(SCGToolsScreenshotOverlay) {}
            SLATE_DEFAULT_SLOT(FArguments, Content)
        SLATE_END_ARGS()

        void Construct(const FArguments& InArgs)
        {
            ChildSlot[InArgs._Content.Widget];
        }

        virtual bool SupportsKeyboardFocus() const override
        {
            return true;
        }

        virtual FReply OnPreviewKeyDown(
            const FGeometry& MyGeometry,
            const FKeyEvent& KeyEvent
        ) override
        {
            if (KeyEvent.GetKey() == EKeys::Escape)
            {
                if (const TSharedPtr<SWindow> Window =
                        FSlateApplication::Get().FindWidgetWindow(AsShared()))
                {
                    Window->RequestDestroyWindow();
                }
                return FReply::Handled().ReleaseMouseCapture();
            }
            return SCompoundWidget::OnPreviewKeyDown(MyGeometry, KeyEvent);
        }
    };

    class SCGToolsScreenshotSelector : public SLeafWidget
    {
    public:
        SLATE_BEGIN_ARGS(SCGToolsScreenshotSelector) {}
            SLATE_ARGUMENT(TArray<FColor>, SourcePixels)
            SLATE_ARGUMENT(FIntPoint, SourceSize)
            SLATE_ARGUMENT(FVector2D, DisplaySize)
        SLATE_END_ARGS()

        void Construct(const FArguments& InArgs)
        {
            SourcePixels = InArgs._SourcePixels;
            SourceSize = InArgs._SourceSize;
            DisplaySize = InArgs._DisplaySize;

            ScreenshotBrush = CreatePreviewBrush(
                SourcePixels,
                SourceSize,
                TEXT("CGToolsPublisher_ScreenshotSource")
            );
        }

        virtual FVector2D ComputeDesiredSize(float) const override
        {
            return DisplaySize;
        }

        virtual bool SupportsKeyboardFocus() const override
        {
            return true;
        }

        void SetOnSelectionAccepted(const FOnClicked& InOnSelectionAccepted)
        {
            OnSelectionAccepted = InOnSelectionAccepted;
        }

        FReply AcceptSelection()
        {
            return OnSelectionAccepted.IsBound()
                ? OnSelectionAccepted.Execute()
                : FReply::Unhandled();
        }

        virtual int32 OnPaint(
            const FPaintArgs& Args,
            const FGeometry& AllottedGeometry,
            const FSlateRect& MyCullingRect,
            FSlateWindowElementList& OutDrawElements,
            int32 LayerId,
            const FWidgetStyle& InWidgetStyle,
            bool bParentEnabled
        ) const override
        {
            if (!ScreenshotBrush.IsValid())
            {
                return LayerId;
            }

            LastWidgetSize = FVector2f(AllottedGeometry.GetLocalSize());

            FSlateDrawElement::MakeBox(
                OutDrawElements,
                LayerId,
                AllottedGeometry.ToPaintGeometry(),
                ScreenshotBrush->GetSlateBrush(),
                ESlateDrawEffect::None,
                FLinearColor::White
            );

            const FVector2f WidgetSize = FVector2f(AllottedGeometry.GetLocalSize());
            const FSlateBrush* WhiteBrush = FCoreStyle::Get().GetBrush(TEXT("WhiteBrush"));
            const FLinearColor DimColor(0.0f, 0.0f, 0.0f, 0.58f);
            const FSlateRect Selection = GetSelectionRect();

            const auto DrawDimRect = [
                &AllottedGeometry,
                &OutDrawElements,
                WhiteBrush,
                DimColor,
                LayerId
            ](float X, float Y, float Width, float Height)
            {
                if (Width <= 0.0f || Height <= 0.0f)
                {
                    return;
                }
                FSlateDrawElement::MakeBox(
                    OutDrawElements,
                    LayerId + 1,
                    AllottedGeometry.ToPaintGeometry(
                        FVector2f(Width, Height),
                        FSlateLayoutTransform(FVector2f(X, Y))
                    ),
                    WhiteBrush,
                    ESlateDrawEffect::None,
                    DimColor
                );
            };

            if (!HasValidSelection())
            {
                DrawDimRect(0.0f, 0.0f, WidgetSize.X, WidgetSize.Y);
            }
            else
            {
                DrawDimRect(0.0f, 0.0f, WidgetSize.X, Selection.Top);
                DrawDimRect(0.0f, Selection.Top, Selection.Left, Selection.Bottom - Selection.Top);
                DrawDimRect(
                    Selection.Right,
                    Selection.Top,
                    WidgetSize.X - Selection.Right,
                    Selection.Bottom - Selection.Top
                );
                DrawDimRect(
                    0.0f,
                    Selection.Bottom,
                    WidgetSize.X,
                    WidgetSize.Y - Selection.Bottom
                );

                TArray<FVector2f> BorderPoints;
                BorderPoints.Reserve(5);
                BorderPoints.Add(FVector2f(Selection.Left, Selection.Top));
                BorderPoints.Add(FVector2f(Selection.Right, Selection.Top));
                BorderPoints.Add(FVector2f(Selection.Right, Selection.Bottom));
                BorderPoints.Add(FVector2f(Selection.Left, Selection.Bottom));
                BorderPoints.Add(FVector2f(Selection.Left, Selection.Top));
                FSlateDrawElement::MakeLines(
                    OutDrawElements,
                    LayerId + 2,
                    AllottedGeometry.ToPaintGeometry(),
                    MoveTemp(BorderPoints),
                    ESlateDrawEffect::None,
                    FLinearColor(0.1f, 1.0f, 0.25f, 1.0f),
                    true,
                    2.0f
                );

                constexpr float HandleSize = 10.0f;
                for (const FVector2f& HandlePosition : GetHandlePositions(Selection))
                {
                    FSlateDrawElement::MakeBox(
                        OutDrawElements,
                        LayerId + 3,
                        AllottedGeometry.ToPaintGeometry(
                            FVector2f(HandleSize, HandleSize),
                            FSlateLayoutTransform(
                                HandlePosition - FVector2f(
                                    HandleSize * 0.5f,
                                    HandleSize * 0.5f
                                )
                            )
                        ),
                        WhiteBrush,
                        ESlateDrawEffect::None,
                        FLinearColor(0.1f, 1.0f, 0.25f, 1.0f)
                    );
                }
            }
            return LayerId + 3;
        }

        virtual FReply OnMouseButtonDown(
            const FGeometry& MyGeometry,
            const FPointerEvent& MouseEvent
        ) override
        {
            if (MouseEvent.GetEffectingButton() != EKeys::LeftMouseButton)
            {
                if (MouseEvent.GetEffectingButton() == EKeys::RightMouseButton
                    && HasValidSelection())
                {
                    ClearSelection();
                    Invalidate(EInvalidateWidgetReason::LayoutAndVolatility);
                    return FReply::Handled();
                }
                return FReply::Unhandled();
            }

            const FVector2f LocalPosition =
                ClampToWidget(MyGeometry, MouseEvent.GetScreenSpacePosition());
            DragStart = LocalPosition;
            InitialSelection = GetSelectionRect();
            ActiveHandle = HitTestHandle(LocalPosition);

            if (ActiveHandle != INDEX_NONE)
            {
                bMovingSelection = false;
                bSelecting = false;
            }
            else if (HasValidSelection() && IsInsideSelection(LocalPosition))
            {
                bMovingSelection = true;
                bSelecting = false;
            }
            else
            {
                ActiveHandle = INDEX_NONE;
                bMovingSelection = false;
                bSelecting = true;
                SelectionStart = LocalPosition;
                SelectionEnd = LocalPosition;
            }
            return FReply::Handled()
                .SetUserFocus(SharedThis(this), EFocusCause::Mouse)
                .CaptureMouse(SharedThis(this));
        }

        virtual FReply OnMouseButtonDoubleClick(
            const FGeometry& MyGeometry,
            const FPointerEvent& MouseEvent
        ) override
        {
            const FVector2f LocalPosition =
                ClampToWidget(MyGeometry, MouseEvent.GetScreenSpacePosition());
            if (MouseEvent.GetEffectingButton() != EKeys::LeftMouseButton
                || !HasValidSelection()
                || !IsInsideSelection(LocalPosition)
                || HitTestHandle(LocalPosition) != INDEX_NONE)
            {
                return FReply::Unhandled();
            }

            bSelecting = false;
            bMovingSelection = false;
            ActiveHandle = INDEX_NONE;
            return AcceptSelection().ReleaseMouseCapture();
        }

        virtual FReply OnMouseMove(
            const FGeometry& MyGeometry,
            const FPointerEvent& MouseEvent
        ) override
        {
            if (!HasMouseCapture())
            {
                return FReply::Unhandled();
            }

            const FVector2f LocalPosition =
                ClampToWidget(MyGeometry, MouseEvent.GetScreenSpacePosition());
            if (ActiveHandle != INDEX_NONE)
            {
                ResizeSelection(LocalPosition);
            }
            else if (bMovingSelection)
            {
                MoveSelection(LocalPosition);
            }
            else if (bSelecting)
            {
                SelectionEnd = LocalPosition;
            }
            else
            {
                return FReply::Unhandled();
            }

            Invalidate(EInvalidateWidgetReason::LayoutAndVolatility);
            return FReply::Handled();
        }

        virtual FReply OnMouseButtonUp(
            const FGeometry& MyGeometry,
            const FPointerEvent& MouseEvent
        ) override
        {
            if (MouseEvent.GetEffectingButton() != EKeys::LeftMouseButton
                || (!bSelecting && !bMovingSelection && ActiveHandle == INDEX_NONE))
            {
                return FReply::Unhandled();
            }
            const FVector2f LocalPosition =
                ClampToWidget(MyGeometry, MouseEvent.GetScreenSpacePosition());
            if (ActiveHandle != INDEX_NONE)
            {
                ResizeSelection(LocalPosition);
            }
            else if (bMovingSelection)
            {
                MoveSelection(LocalPosition);
            }
            else if (bSelecting)
            {
                SelectionEnd = LocalPosition;
            }

            bSelecting = false;
            bMovingSelection = false;
            ActiveHandle = INDEX_NONE;
            Invalidate(EInvalidateWidgetReason::LayoutAndVolatility);
            return FReply::Handled().ReleaseMouseCapture();
        }

        virtual FCursorReply OnCursorQuery(
            const FGeometry& MyGeometry,
            const FPointerEvent& CursorEvent
        ) const override
        {
            const FVector2f LocalPosition = FVector2f(
                MyGeometry.AbsoluteToLocal(CursorEvent.GetScreenSpacePosition())
            );
            const int32 Handle = HitTestHandle(LocalPosition);
            if (Handle == 0 || Handle == 7)
            {
                return FCursorReply::Cursor(EMouseCursor::ResizeSouthEast);
            }
            if (Handle == 2 || Handle == 5)
            {
                return FCursorReply::Cursor(EMouseCursor::ResizeSouthWest);
            }
            if (Handle == 1 || Handle == 6)
            {
                return FCursorReply::Cursor(EMouseCursor::ResizeUpDown);
            }
            if (Handle == 3 || Handle == 4)
            {
                return FCursorReply::Cursor(EMouseCursor::ResizeLeftRight);
            }
            if (HasValidSelection() && IsInsideSelection(LocalPosition))
            {
                return FCursorReply::Cursor(EMouseCursor::CardinalCross);
            }
            return FCursorReply::Cursor(EMouseCursor::Crosshairs);
        }

        bool GetSelectedPixels(TArray<FColor>& OutPixels, FIntPoint& OutSize) const
        {
            if (!HasValidSelection()
                || SourceSize.X <= 0
                || SourceSize.Y <= 0
                || SourcePixels.Num() < SourceSize.X * SourceSize.Y)
            {
                return false;
            }

            const FSlateRect Selection = GetSelectionRect();
            const FVector2f SelectionSurfaceSize =
                LastWidgetSize.X > 0.0f && LastWidgetSize.Y > 0.0f
                    ? LastWidgetSize
                    : FVector2f(DisplaySize);
            const float ScaleX =
                static_cast<float>(SourceSize.X) / SelectionSurfaceSize.X;
            const float ScaleY =
                static_cast<float>(SourceSize.Y) / SelectionSurfaceSize.Y;
            const int32 MinX = FMath::Clamp(FMath::FloorToInt(Selection.Left * ScaleX), 0, SourceSize.X - 1);
            const int32 MinY = FMath::Clamp(FMath::FloorToInt(Selection.Top * ScaleY), 0, SourceSize.Y - 1);
            const int32 MaxX = FMath::Clamp(FMath::CeilToInt(Selection.Right * ScaleX), MinX + 1, SourceSize.X);
            const int32 MaxY = FMath::Clamp(FMath::CeilToInt(Selection.Bottom * ScaleY), MinY + 1, SourceSize.Y);

            OutSize = FIntPoint(MaxX - MinX, MaxY - MinY);
            OutPixels.SetNumUninitialized(OutSize.X * OutSize.Y);
            for (int32 Y = 0; Y < OutSize.Y; ++Y)
            {
                FMemory::Memcpy(
                    OutPixels.GetData() + Y * OutSize.X,
                    SourcePixels.GetData() + (MinY + Y) * SourceSize.X + MinX,
                    OutSize.X * sizeof(FColor)
                );
            }
            return true;
        }

        bool HasValidSelection() const
        {
            const FSlateRect Selection = GetSelectionRect();
            return Selection.Right - Selection.Left >= 5.0f
                && Selection.Bottom - Selection.Top >= 5.0f;
        }

        FVector2D GetToolbarPosition(float ToolbarWidth, float ToolbarHeight) const
        {
            const FSlateRect Selection = GetSelectionRect();
            const FVector2f SurfaceSize = LastWidgetSize.X > 0.0f
                && LastWidgetSize.Y > 0.0f
                    ? LastWidgetSize
                    : FVector2f(DisplaySize);
            float X = FMath::Clamp(
                Selection.Left,
                0.0f,
                FMath::Max(0.0f, SurfaceSize.X - ToolbarWidth)
            );
            float Y = Selection.Bottom + 8.0f;
            if (Y + ToolbarHeight > SurfaceSize.Y)
            {
                Y = Selection.Top - ToolbarHeight - 8.0f;
            }
            Y = FMath::Clamp(
                Y,
                0.0f,
                FMath::Max(0.0f, SurfaceSize.Y - ToolbarHeight)
            );
            return FVector2D(X, Y);
        }

    private:
        TArray<FColor> SourcePixels;
        FIntPoint SourceSize = FIntPoint::ZeroValue;
        FVector2D DisplaySize = FVector2D::ZeroVector;
        TSharedPtr<FDeferredCleanupSlateBrush> ScreenshotBrush;
        mutable FVector2f LastWidgetSize = FVector2f::ZeroVector;
        FVector2f SelectionStart = FVector2f::ZeroVector;
        FVector2f SelectionEnd = FVector2f::ZeroVector;
        FVector2f DragStart = FVector2f::ZeroVector;
        FSlateRect InitialSelection = FSlateRect(0, 0, 0, 0);
        int32 ActiveHandle = INDEX_NONE;
        bool bSelecting = false;
        bool bMovingSelection = false;
        FOnClicked OnSelectionAccepted;

        static TArray<FVector2f> GetHandlePositions(const FSlateRect& Selection)
        {
            const float CenterX = (Selection.Left + Selection.Right) * 0.5f;
            const float CenterY = (Selection.Top + Selection.Bottom) * 0.5f;
            return {
                FVector2f(Selection.Left, Selection.Top),
                FVector2f(CenterX, Selection.Top),
                FVector2f(Selection.Right, Selection.Top),
                FVector2f(Selection.Left, CenterY),
                FVector2f(Selection.Right, CenterY),
                FVector2f(Selection.Left, Selection.Bottom),
                FVector2f(CenterX, Selection.Bottom),
                FVector2f(Selection.Right, Selection.Bottom)
            };
        }

        int32 HitTestHandle(const FVector2f& Position) const
        {
            if (!HasValidSelection())
            {
                return INDEX_NONE;
            }

            constexpr float HitRadius = 9.0f;
            const TArray<FVector2f> Handles = GetHandlePositions(GetSelectionRect());
            for (int32 Index = 0; Index < Handles.Num(); ++Index)
            {
                if (FMath::Abs(Position.X - Handles[Index].X) <= HitRadius
                    && FMath::Abs(Position.Y - Handles[Index].Y) <= HitRadius)
                {
                    return Index;
                }
            }
            return INDEX_NONE;
        }

        bool IsInsideSelection(const FVector2f& Position) const
        {
            const FSlateRect Selection = GetSelectionRect();
            return Position.X >= Selection.Left
                && Position.X <= Selection.Right
                && Position.Y >= Selection.Top
                && Position.Y <= Selection.Bottom;
        }

        void SetSelectionRect(const FSlateRect& Selection)
        {
            SelectionStart = FVector2f(Selection.Left, Selection.Top);
            SelectionEnd = FVector2f(Selection.Right, Selection.Bottom);
        }

        void ClearSelection()
        {
            SelectionStart = FVector2f::ZeroVector;
            SelectionEnd = FVector2f::ZeroVector;
            ActiveHandle = INDEX_NONE;
            bSelecting = false;
            bMovingSelection = false;
        }

        void MoveSelection(const FVector2f& LocalPosition)
        {
            const float Width = InitialSelection.Right - InitialSelection.Left;
            const float Height = InitialSelection.Bottom - InitialSelection.Top;
            const float Left = FMath::Clamp(
                InitialSelection.Left + LocalPosition.X - DragStart.X,
                0.0f,
                FMath::Max(0.0f, LastWidgetSize.X - Width)
            );
            const float Top = FMath::Clamp(
                InitialSelection.Top + LocalPosition.Y - DragStart.Y,
                0.0f,
                FMath::Max(0.0f, LastWidgetSize.Y - Height)
            );
            SetSelectionRect(FSlateRect(Left, Top, Left + Width, Top + Height));
        }

        void ResizeSelection(const FVector2f& LocalPosition)
        {
            FSlateRect Resized = InitialSelection;
            switch (ActiveHandle)
            {
            case 0: Resized.Left = LocalPosition.X; Resized.Top = LocalPosition.Y; break;
            case 1: Resized.Top = LocalPosition.Y; break;
            case 2: Resized.Right = LocalPosition.X; Resized.Top = LocalPosition.Y; break;
            case 3: Resized.Left = LocalPosition.X; break;
            case 4: Resized.Right = LocalPosition.X; break;
            case 5: Resized.Left = LocalPosition.X; Resized.Bottom = LocalPosition.Y; break;
            case 6: Resized.Bottom = LocalPosition.Y; break;
            case 7: Resized.Right = LocalPosition.X; Resized.Bottom = LocalPosition.Y; break;
            default: return;
            }

            SetSelectionRect(FSlateRect(
                FMath::Min(Resized.Left, Resized.Right),
                FMath::Min(Resized.Top, Resized.Bottom),
                FMath::Max(Resized.Left, Resized.Right),
                FMath::Max(Resized.Top, Resized.Bottom)
            ));
        }

        FVector2f ClampToWidget(const FGeometry& Geometry, const FVector2D& ScreenPosition) const
        {
            const FVector2D LocalPosition = Geometry.AbsoluteToLocal(ScreenPosition);
            const FVector2D LocalSize = Geometry.GetLocalSize();
            return FVector2f(
                FMath::Clamp(static_cast<float>(LocalPosition.X), 0.0f, static_cast<float>(LocalSize.X)),
                FMath::Clamp(static_cast<float>(LocalPosition.Y), 0.0f, static_cast<float>(LocalSize.Y))
            );
        }

        FSlateRect GetSelectionRect() const
        {
            return FSlateRect(
                FMath::Min(SelectionStart.X, SelectionEnd.X),
                FMath::Min(SelectionStart.Y, SelectionEnd.Y),
                FMath::Max(SelectionStart.X, SelectionEnd.X),
                FMath::Max(SelectionStart.Y, SelectionEnd.Y)
            );
        }
    };

    bool SaveJsonFile(const FString& Filename, const TSharedRef<FJsonObject>& Object, FString& OutError)
    {
        FString JsonText;
        const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&JsonText);
        if (!FJsonSerializer::Serialize(Object, Writer))
        {
            OutError = TEXT("无法序列化 .uproject 内容。");
            return false;
        }

        IPlatformFile& PlatformFile = FPlatformFileManager::Get().GetPlatformFile();
        const FString ParentDirectory = FPaths::GetPath(Filename);
        if (ParentDirectory.IsEmpty()
            || (!PlatformFile.DirectoryExists(*ParentDirectory)
                && !PlatformFile.CreateDirectoryTree(*ParentDirectory))
            || !PlatformFile.DirectoryExists(*ParentDirectory))
        {
            OutError = FString::Printf(TEXT("无法建立项目文件目录：%s"), *ParentDirectory);
            return false;
        }

        // The project file is written inside a unique staging directory, so an
        // additional temporary-file rename gives us no safety benefit. Renaming
        // a freshly written file is also unreliable on some mapped SMB shares.
        if (!FFileHelper::SaveStringToFile(
                JsonText,
                *Filename,
                FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM
            ))
        {
            OutError = FString::Printf(TEXT("无法写入项目文件：%s"), *Filename);
            return false;
        }

        if (!PlatformFile.FileExists(*Filename) || PlatformFile.FileSize(*Filename) <= 0)
        {
            PlatformFile.DeleteFile(*Filename);
            OutError = FString::Printf(TEXT("项目文件写入后校验失败：%s"), *Filename);
            return false;
        }
        return true;
    }

    bool CopyFileChecked(IPlatformFile& PlatformFile, const FString& Destination, const FString& Source)
    {
        PlatformFile.CreateDirectoryTree(*FPaths::GetPath(Destination));
        return PlatformFile.CopyFile(*Destination, *Source)
            && PlatformFile.FileExists(*Destination)
            && PlatformFile.FileSize(*Destination) > 0;
    }

}

namespace CGToolsPublisher
{
    bool RepairSourceAssetDisplay(
        const TArray<FString>& VirtualFolders,
        FString& OutMessage)
    {
        OutMessage.Reset();
        FModuleManager::Get().LoadModule(TEXT("AssetRegistryRepair"));

        UClass* RepairLibraryClass = FindObject<UClass>(
            nullptr,
            TEXT("/Script/AssetRegistryRepair.AssetRegistryRepairLibrary")
        );
        if (!RepairLibraryClass)
        {
            OutMessage = TEXT("AssetRegistryRepair 模块已加载，但没有找到修复函数库类。");
            return false;
        }

        UFunction* RepairFunction = RepairLibraryClass->FindFunctionByName(
            TEXT("RepairAssetRegistryFromDiskInFolders")
        );
        UObject* RepairLibraryObject = RepairLibraryClass->GetDefaultObject();
        if (!RepairFunction || !RepairLibraryObject)
        {
            OutMessage = TEXT("AssetRegistryRepair 没有公开 RepairAssetRegistryFromDiskInFolders。");
            return false;
        }

        FArrayProperty* FoldersProperty = FindFProperty<FArrayProperty>(
            RepairFunction,
            TEXT("VirtualFolders")
        );
        FIntProperty* ModifiedMinutesProperty = FindFProperty<FIntProperty>(
            RepairFunction,
            TEXT("ModifiedWithinMinutes")
        );
        FBoolProperty* IncludeMapsProperty = FindFProperty<FBoolProperty>(
            RepairFunction,
            TEXT("bIncludeMaps")
        );
        FBoolProperty* ForceLoadProperty = FindFProperty<FBoolProperty>(
            RepairFunction,
            TEXT("bForceLoadMissingPackages")
        );
        FIntProperty* MaxLoadProperty = FindFProperty<FIntProperty>(
            RepairFunction,
            TEXT("MaxPackagesToLoad")
        );
        FIntProperty* MaxSyncProperty = FindFProperty<FIntProperty>(
            RepairFunction,
            TEXT("MaxAssetsToSync")
        );
        FStructProperty* ReturnProperty = FindFProperty<FStructProperty>(
            RepairFunction,
            TEXT("ReturnValue")
        );
        if (!FoldersProperty
            || !ModifiedMinutesProperty
            || !IncludeMapsProperty
            || !ForceLoadProperty
            || !MaxLoadProperty
            || !MaxSyncProperty
            || !ReturnProperty
            || !ReturnProperty->Struct)
        {
            OutMessage = TEXT("AssetRegistryRepair 的函数参数与发布器预期不一致。");
            return false;
        }

        FBoolProperty* SucceededProperty = FindFProperty<FBoolProperty>(
            ReturnProperty->Struct,
            TEXT("bSucceeded")
        );
        FStrProperty* MessageProperty = FindFProperty<FStrProperty>(
            ReturnProperty->Struct,
            TEXT("Message")
        );
        if (!SucceededProperty || !MessageProperty)
        {
            OutMessage = TEXT("AssetRegistryRepair 的返回结果结构与发布器预期不一致。");
            return false;
        }

        FStructOnScope Parameters(RepairFunction);
        if (!Parameters.IsValid())
        {
            OutMessage = TEXT("无法建立 AssetRegistryRepair 的反射参数。");
            return false;
        }

        uint8* ParameterMemory = Parameters.GetStructMemory();
        FoldersProperty->CopyCompleteValue(
            FoldersProperty->ContainerPtrToValuePtr<void>(ParameterMemory),
            &VirtualFolders
        );
        ModifiedMinutesProperty->SetPropertyValue_InContainer(ParameterMemory, 0);
        IncludeMapsProperty->SetPropertyValue_InContainer(ParameterMemory, false);
        ForceLoadProperty->SetPropertyValue_InContainer(ParameterMemory, true);
        MaxLoadProperty->SetPropertyValue_InContainer(ParameterMemory, 2000);
        MaxSyncProperty->SetPropertyValue_InContainer(ParameterMemory, 30);

        RepairLibraryObject->ProcessEvent(RepairFunction, ParameterMemory);

        const void* ResultMemory =
            ReturnProperty->ContainerPtrToValuePtr<void>(ParameterMemory);
        const bool bSucceeded =
            SucceededProperty->GetPropertyValue_InContainer(ResultMemory);
        OutMessage = MessageProperty->GetPropertyValue_InContainer(ResultMemory);
        return bSucceeded;
    }
}

void SCGToolsPublisherWindow::Construct(const FArguments& InArgs)
{
    AssetData = InArgs._AssetData;
    DialogState = InArgs._DialogState.IsValid() ? InArgs._DialogState : MakeShared<FCGToolsPublisherDialogState>();
    UObject* Asset = AssetData.GetAsset();
    PublishAsset.Reset(Asset);
    bSkeletalMeshPublish = Asset && Asset->IsA<USkeletalMesh>();
    Config = LoadConfig();

    for (const FString& Project : Config.Projects)
    {
        ProjectOptions.Add(MakeShared<FString>(Project));
    }
    RefreshTypes();

    ThumbnailPool = MakeShared<FAssetThumbnailPool>(1);
    AssetThumbnail = MakeShared<FAssetThumbnail>(AssetData, 256, 256, ThumbnailPool);
    BuildAutomaticIcon(Asset);

    FString InitialAssetName = AssetData.AssetName.ToString();
    FString FolderType;
    FString FolderError;
    if (!ResolveMeshAssetFolder(FolderType, InitialAssetName, FolderError))
    {
        InitialAssetName = FPaths::GetCleanFilename(AssetData.PackagePath.ToString());
    }
    const FString PublisherName = ReadPublisherName();

    ChildSlot
    [
        SNew(SBorder)
        .BorderImage(FAppStyle::GetBrush("ToolPanel.GroupBorder"))
        .Padding(14.0f)
        [
            SNew(SVerticalBox)

            + SVerticalBox::Slot()
            .AutoHeight()
            .Padding(0.0f, 0.0f, 0.0f, 12.0f)
            [
                SNew(STextBlock)
                .Text_Lambda([this]()
                {
                    return FText::FromString(GetAssetKindLabel() + TEXT("发布"));
                })
                .Font(FAppStyle::GetFontStyle("HeadingExtraSmall"))
            ]

            + SVerticalBox::Slot()
            .FillHeight(1.0f)
            [
                SNew(SSplitter)
                .PhysicalSplitterHandleSize(5.0f)
                .HitDetectionSplitterHandleSize(9.0f)

                + SSplitter::Slot()
                .Value(0.37f)
                .MinSize(260.0f)
                [
                    SNew(SBorder)
                    .BorderImage(FAppStyle::GetBrush("NoBrush"))
                    .Padding(FMargin(0.0f, 0.0f, 10.0f, 0.0f))
                    [
                        SNew(SVerticalBox)

                    + SVerticalBox::Slot()
                    .AutoHeight()
                    [
                        SNew(SBox)
                        .WidthOverride(256.0f)
                        .HeightOverride(256.0f)
                        [
                            SNew(SBorder)
                            .BorderImage(FAppStyle::GetBrush("Brushes.Recessed"))
                            .Padding(0.0f)
                            [
                                SNew(SOverlay)
                                + SOverlay::Slot()
                                [
                                    SNew(SScaleBox)
                                    .Stretch(EStretch::ScaleToFit)
                                    .Visibility_Lambda([this]()
                                    {
                                        return CustomIconPixels.Num() == 0
                                            && AutomaticIconBrush.IsValid()
                                            ? EVisibility::Visible
                                            : EVisibility::Collapsed;
                                    })
                                    [
                                        SNew(SImage)
                                        .Image(this, &SCGToolsPublisherWindow::GetAutomaticIconBrush)
                                    ]
                                ]
                                + SOverlay::Slot()
                                [
                                    SNew(SBox)
                                    .Visibility_Lambda([this]()
                                    {
                                        return CustomIconPixels.Num() == 0
                                            && !AutomaticIconBrush.IsValid()
                                            ? EVisibility::Visible
                                            : EVisibility::Collapsed;
                                    })
                                    [
                                        AssetThumbnail->MakeThumbnailWidget()
                                    ]
                                ]
                                + SOverlay::Slot()
                                [
                                    SNew(SScaleBox)
                                    .Stretch(EStretch::ScaleToFit)
                                    .Visibility_Lambda([this]()
                                    {
                                        return CustomIconPixels.Num() > 0
                                            ? EVisibility::Visible
                                            : EVisibility::Collapsed;
                                    })
                                    [
                                        SNew(SImage)
                                        .Image(this, &SCGToolsPublisherWindow::GetCustomIconBrush)
                                    ]
                                ]
                            ]
                        ]
                    ]

                    + SVerticalBox::Slot()
                    .AutoHeight()
                    .Padding(0.0f, 7.0f, 0.0f, 0.0f)
                    [
                        SNew(SHorizontalBox)
                        + SHorizontalBox::Slot()
                        .FillWidth(1.0f)
                        [
                            SNew(SButton)
                            .Text(LOCTEXT("CaptureIcon", "框选截图"))
                            .ToolTipText(LOCTEXT(
                                "CaptureIconTooltip",
                                "进入原屏截图模式，在任意显示器上框选 Icon；建议选择正方形区域。"
                            ))
                            .IsEnabled_Lambda([this]() { return !bIsPublishing; })
                            .OnClicked(this, &SCGToolsPublisherWindow::OnCaptureIconClicked)
                        ]
                        + SHorizontalBox::Slot()
                        .FillWidth(1.0f)
                        .Padding(6.0f, 0.0f, 0.0f, 0.0f)
                        [
                            SNew(SButton)
                            .Text(LOCTEXT("UseAssetThumbnail", "恢复缩略图"))
                            .ToolTipText(LOCTEXT(
                                "UseAssetThumbnailTooltip",
                                "清除框选截图，恢复使用 UE 自动生成的资产缩略图。"
                            ))
                            .IsEnabled_Lambda([this]()
                            {
                                return !bIsPublishing && CustomIconPixels.Num() > 0;
                            })
                            .OnClicked(this, &SCGToolsPublisherWindow::OnUseAssetThumbnailClicked)
                        ]
                    ]

                    + SVerticalBox::Slot()
                    .AutoHeight()
                    .Padding(0.0f, 5.0f, 0.0f, 0.0f)
                    [
                        SNew(STextBlock)
                        .Text_Lambda([this]()
                        {
                            return CustomIconPixels.Num() > 0
                                ? LOCTEXT("CapturedIconActive", "Icon：框选截图")
                                : LOCTEXT("AssetThumbnailActive", "Icon：UE 资产缩略图");
                        })
                        .Justification(ETextJustify::Center)
                        .ColorAndOpacity(FSlateColor::UseSubduedForeground())
                    ]

                    + SVerticalBox::Slot()
                    .AutoHeight()
                    .Padding(0.0f, 7.0f, 0.0f, 0.0f)
                    [
                        SNew(STextBlock)
                        .Text(FText::FromName(AssetData.AssetName))
                        .Justification(ETextJustify::Center)
                    ]

                    + SVerticalBox::Slot()
                    .AutoHeight()
                    .Padding(0.0f, 3.0f, 0.0f, 0.0f)
                    [
                        SNew(STextBlock)
                        .Text(FText::FromString(AssetData.PackageName.ToString()))
                        .ColorAndOpacity(FSlateColor::UseSubduedForeground())
                        .AutoWrapText(true)
                    ]
                    ]
                ]

                + SSplitter::Slot()
                .Value(0.63f)
                .MinSize(280.0f)
                [
                    SNew(SBorder)
                    .BorderImage(FAppStyle::GetBrush("NoBrush"))
                    .Padding(FMargin(10.0f, 0.0f, 0.0f, 0.0f))
                    [
                        SNew(SScrollBox)

                    + SScrollBox::Slot()
                    [
                        SNew(SGridPanel)
                        .FillColumn(1, 1.0f)

                        + SGridPanel::Slot(0, 0)
                        .Padding(0.0f, 4.0f, 12.0f, 4.0f)
                        .VAlign(VAlign_Center)
                        [
                            SNew(STextBlock).Text(LOCTEXT("ProjectLabel", "项目"))
                        ]
                        + SGridPanel::Slot(1, 0)
                        .Padding(0.0f, 4.0f)
                        [
                            SAssignNew(ProjectCombo, SComboBox<TSharedPtr<FString>>)
                            .OptionsSource(&ProjectOptions)
                            .InitiallySelectedItem(SelectedProject)
                            .OnGenerateWidget(this, &SCGToolsPublisherWindow::GenerateComboItem)
                            .OnSelectionChanged(this, &SCGToolsPublisherWindow::OnProjectChanged)
                            [
                                SNew(STextBlock).Text(this, &SCGToolsPublisherWindow::GetProjectComboText)
                            ]
                        ]

                        + SGridPanel::Slot(0, 1)
                        .Padding(0.0f, 4.0f, 12.0f, 4.0f)
                        .VAlign(VAlign_Center)
                        [
                            SNew(STextBlock).Text(LOCTEXT("TypeLabel", "类型"))
                        ]
                        + SGridPanel::Slot(1, 1)
                        .Padding(0.0f, 4.0f)
                        [
                            SNew(SHorizontalBox)
                            + SHorizontalBox::Slot()
                            .AutoWidth()
                            .VAlign(VAlign_Center)
                            .Padding(0.0f, 0.0f, 5.0f, 0.0f)
                            [
                                SNew(STextBlock)
                                .Text(this, &SCGToolsPublisherWindow::GetPublishBaseFolderPrefixText)
                                .ColorAndOpacity(FSlateColor::UseSubduedForeground())
                            ]
                            + SHorizontalBox::Slot()
                            .FillWidth(1.0f)
                            [
                                SAssignNew(TypeCombo, SComboBox<TSharedPtr<FString>>)
                                .OptionsSource(&TypeOptions)
                                .InitiallySelectedItem(SelectedType)
                                .IsEnabled_Lambda([this]() { return SelectedProject.IsValid(); })
                                .OnGenerateWidget(this, &SCGToolsPublisherWindow::GenerateComboItem)
                                .OnSelectionChanged(this, &SCGToolsPublisherWindow::OnTypeChanged)
                                [
                                    SAssignNew(TypeTextBox, SEditableText)
                                    .Text(FText::FromString(GetSelectedType()))
                                    .HintText(LOCTEXT("TypeHint", "选择或输入新类型"))
                                    .IsReadOnly(bSkeletalMeshPublish)
                                    .OnTextChanged(this, &SCGToolsPublisherWindow::OnTypeTextChanged)
                                ]
                            ]
                        ]

                        + SGridPanel::Slot(0, 2)
                        .Padding(0.0f, 4.0f, 12.0f, 4.0f)
                        .VAlign(VAlign_Center)
                        [
                            SNew(STextBlock).Text(LOCTEXT("AssetNameLabel", "资产名"))
                        ]
                        + SGridPanel::Slot(1, 2)
                        .Padding(0.0f, 4.0f)
                        [
                            SAssignNew(AssetNameTextBox, SEditableTextBox)
                            .Text(FText::FromString(InitialAssetName))
                            .IsReadOnly(true)
                            .ToolTipText(LOCTEXT("AssetFolderNameTooltip", "资产名使用所属资产文件夹名；同目录中的模型发布到同一个资产。"))
                            .OnTextChanged(this, &SCGToolsPublisherWindow::OnAssetNameChanged)
                        ]

                        + SGridPanel::Slot(0, 3)
                        .Padding(0.0f, 4.0f, 12.0f, 4.0f)
                        .VAlign(VAlign_Center)
                        [
                            SNew(STextBlock).Text(LOCTEXT("ChineseNameLabel", "中文名"))
                        ]
                        + SGridPanel::Slot(1, 3)
                        .Padding(0.0f, 4.0f)
                        [
                             SAssignNew(ChineseNameTextBox, SEditableTextBox)
                             .Text(FText::GetEmpty())
                             .HintText(LOCTEXT("ChineseNameHint", "留空保留原中文名"))
                         ]

                        + SGridPanel::Slot(0, 4)
                        .Padding(0.0f, 4.0f, 12.0f, 4.0f)
                        .VAlign(VAlign_Center)
                        [
                            SNew(STextBlock).Text(LOCTEXT("PublisherLabel", "发布者"))
                        ]
                        + SGridPanel::Slot(1, 4)
                        .Padding(0.0f, 4.0f)
                        .VAlign(VAlign_Center)
                        [
                            SNew(STextBlock)
                            .Text(FText::FromString(PublisherName.IsEmpty() ? TEXT("未登录 ShotManager") : PublisherName))
                            .ColorAndOpacity(PublisherName.IsEmpty()
                                ? FSlateColor(FLinearColor(1.0f, 0.35f, 0.15f))
                                : FSlateColor::UseForeground())
                        ]

                        + SGridPanel::Slot(0, 5)
                        .Padding(0.0f, 8.0f, 12.0f, 4.0f)
                        .VAlign(VAlign_Top)
                        [
                            SNew(STextBlock).Text(LOCTEXT("OptionsLabel", "发布内容"))
                        ]
                        + SGridPanel::Slot(1, 5)
                        .Padding(0.0f, 8.0f, 0.0f, 4.0f)
                        [
                            SNew(SVerticalBox)
                            + SVerticalBox::Slot()
                            .AutoHeight()
                            [
                                SAssignNew(PublishIconCheckBox, SCheckBox)
                                .IsChecked(ECheckBoxState::Checked)
                                .OnCheckStateChanged_Lambda([this](ECheckBoxState)
                                {
                                    RefreshTargetPath();
                                })
                                [
                                    SNew(STextBlock).Text(LOCTEXT("PublishIcon", "发布 Icon"))
                                ]
                            ]
                            + SVerticalBox::Slot()
                            .AutoHeight()
                            .Padding(0.0f, 5.0f, 0.0f, 0.0f)
                            [
                                SAssignNew(PublishFbxCheckBox, SCheckBox)
                                .IsChecked(ECheckBoxState::Checked)
                                .OnCheckStateChanged_Lambda([this](ECheckBoxState)
                                {
                                    RefreshTargetPath();
                                })
                                [
                                    SNew(STextBlock).Text(LOCTEXT("PublishFbx", "发布 FBX"))
                                ]
                            ]
                            + SVerticalBox::Slot()
                            .AutoHeight()
                            .Padding(0.0f, 5.0f, 0.0f, 0.0f)
                            [
                                SAssignNew(PublishTextureCheckBox, SCheckBox)
                                .IsChecked(ECheckBoxState::Unchecked)
                                .OnCheckStateChanged_Lambda([this](ECheckBoxState)
                                {
                                    RefreshTargetPath();
                                })
                                [
                                    SNew(STextBlock).Text(LOCTEXT("PublishTexture", "发布 Texture"))
                                ]
                            ]
                        ]

                        + SGridPanel::Slot(0, 6)
                        .ColumnSpan(2)
                        .Padding(0.0f, 14.0f, 0.0f, 4.0f)
                        [
                            SNew(STextBlock)
                            .Text(LOCTEXT("TargetPathLabel", "发布目标"))
                            .Font(FAppStyle::GetFontStyle("NormalFontBold"))
                        ]

                        + SGridPanel::Slot(0, 7)
                        .ColumnSpan(2)
                        .Padding(0.0f, 2.0f, 0.0f, 8.0f)
                        [
                            SNew(SBorder)
                            .BorderImage(FAppStyle::GetBrush("Brushes.Recessed"))
                            .Padding(8.0f)
                            [
                                SAssignNew(TargetPathText, STextBlock)
                                .AutoWrapText(true)
                                .ColorAndOpacity(FSlateColor::UseSubduedForeground())
                            ]
                        ]

                        + SGridPanel::Slot(0, 8)
                        .ColumnSpan(2)
                        .Padding(0.0f, 6.0f, 0.0f, 3.0f)
                        [
                            SNew(SBox)
                            .HeightOverride(10.0f)
                            [
                                SAssignNew(ProgressBar, SProgressBar)
                                .Percent_Lambda([this]() { return Progress; })
                            ]
                        ]

                        + SGridPanel::Slot(0, 9)
                        .ColumnSpan(2)
                        .Padding(0.0f, 3.0f, 0.0f, 0.0f)
                        [
                            SNew(SHorizontalBox)
                            + SHorizontalBox::Slot()
                            .AutoWidth()
                            .VAlign(VAlign_Center)
                            .Padding(0.0f, 0.0f, 6.0f, 0.0f)
                            [
                                SNew(SThrobber)
                                .NumPieces(3)
                                .Visibility_Lambda([this]()
                                {
                                    return bIsPublishing
                                        ? EVisibility::Visible
                                        : EVisibility::Collapsed;
                                })
                            ]
                            + SHorizontalBox::Slot()
                            .FillWidth(1.0f)
                            .VAlign(VAlign_Center)
                            [
                                SAssignNew(StatusText, STextBlock)
                                .Text(Config.IsValid()
                                    ? LOCTEXT("Ready", "准备发布")
                                    : FText::FromString(Config.Error))
                                .AutoWrapText(true)
                                .ColorAndOpacity_Lambda([this]()
                                {
                                    if (bIsPublishing)
                                    {
                                        return FSlateColor::UseForeground();
                                    }
                                    return Config.IsValid()
                                        ? FSlateColor::UseSubduedForeground()
                                        : FSlateColor(FLinearColor(1.0f, 0.25f, 0.15f));
                                })
                            ]
                            + SHorizontalBox::Slot()
                            .AutoWidth()
                            .VAlign(VAlign_Center)
                            .Padding(8.0f, 0.0f, 0.0f, 0.0f)
                            [
                                SNew(STextBlock)
                                .Text_Lambda([this]()
                                {
                                    const float Value = Progress.IsSet()
                                        ? Progress.GetValue()
                                        : 0.0f;
                                    return FText::AsPercent(Value);
                                })
                                .Visibility_Lambda([this]()
                                {
                                    return bIsPublishing
                                        ? EVisibility::Visible
                                        : EVisibility::Collapsed;
                                })
                            ]
                        ]
                    ]
                    ]
                ]
            ]

            + SVerticalBox::Slot()
            .AutoHeight()
            .Padding(0.0f, 14.0f, 0.0f, 0.0f)
            .HAlign(HAlign_Right)
            [
                SNew(SHorizontalBox)
                .Visibility(DialogState->bEmbedded ? EVisibility::Collapsed : EVisibility::Visible)
                + SHorizontalBox::Slot()
                .AutoWidth()
                .Padding(0.0f, 0.0f, 8.0f, 0.0f)
                [
                    SNew(SButton)
                    .Text(LOCTEXT("SkipCurrent", "跳过当前"))
                    .Visibility(DialogState->IsBatch() ? EVisibility::Visible : EVisibility::Collapsed)
                    .IsEnabled_Lambda([this]() { return !bIsPublishing; })
                    .OnClicked(this, &SCGToolsPublisherWindow::OnSkipClicked)
                ]
                + SHorizontalBox::Slot()
                .AutoWidth()
                [
                    SNew(SButton)
                    .Text(DialogState->IsBatch() ? LOCTEXT("EndBatch", "结束批量发布") : LOCTEXT("Cancel", "取消"))
                    .IsEnabled_Lambda([this]() { return !bIsPublishing; })
                    .OnClicked(this, &SCGToolsPublisherWindow::OnCancelClicked)
                ]
                + SHorizontalBox::Slot()
                .AutoWidth()
                .Padding(8.0f, 0.0f, 0.0f, 0.0f)
                [
                    SNew(SButton)
                    .ButtonStyle(FAppStyle::Get(), "PrimaryButton")
                    .Text(LOCTEXT("Publish", "确定发布"))
                    .IsEnabled(this, &SCGToolsPublisherWindow::CanPublish)
                    .OnClicked(this, &SCGToolsPublisherWindow::OnPublishClicked)
                ]
            ]
        ]
    ];

    RefreshTargetPath();
}

FCGToolsPublisherConfig SCGToolsPublisherWindow::LoadConfig()
{
    FCGToolsPublisherConfig Result;
    FString JsonText;
    if (!FFileHelper::LoadFileToString(JsonText, CommonSettingPath))
    {
        Result.Error = FString::Printf(
            TEXT("无法读取通用配置：%s\n请检查 Y: 映射和服务器权限。"),
            CommonSettingPath
        );
        return Result;
    }

    TSharedPtr<FJsonObject> RootObject;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonText);
    if (!FJsonSerializer::Deserialize(Reader, RootObject) || !RootObject.IsValid())
    {
        Result.Error = FString::Printf(TEXT("通用配置不是有效 JSON：%s"), CommonSettingPath);
        return Result;
    }

    RootObject->TryGetStringField(TEXT("rootPath"), Result.RootPath);
    RootObject->TryGetStringField(TEXT("host"), Result.Host);
    RootObject->TryGetStringField(TEXT("scenesFolder"), Result.ScenesFolder);
    RootObject->TryGetStringField(TEXT("assetsFolder"), Result.AssetsFolder);
    Result.RootPath.TrimStartAndEndInline();
    Result.Host.TrimStartAndEndInline();
    Result.ScenesFolder.TrimStartAndEndInline();
    Result.AssetsFolder.TrimStartAndEndInline();
    if (Result.ScenesFolder.IsEmpty())
    {
        Result.ScenesFolder = TEXT("Scenes");
    }
    if (Result.AssetsFolder.IsEmpty())
    {
        Result.AssetsFolder = TEXT("Assets");
    }

    const TArray<TSharedPtr<FJsonValue>>* ProjectValues = nullptr;
    if (RootObject->TryGetArrayField(TEXT("DataBase"), ProjectValues) && ProjectValues)
    {
        for (const TSharedPtr<FJsonValue>& Value : *ProjectValues)
        {
            FString Project;
            if (Value.IsValid() && Value->TryGetString(Project))
            {
                Project.TrimStartAndEndInline();
                if (!Project.IsEmpty())
                {
                    Result.Projects.AddUnique(Project);
                }
            }
        }
    }

    if (Result.RootPath.IsEmpty())
    {
        Result.Error = TEXT("commonSetting.json 缺少 rootPath 字段。");
    }
    else if (Result.Host.IsEmpty())
    {
        Result.Error = TEXT("commonSetting.json 缺少有效的 host 数据库地址，请填写数据库 DNS 名或 IP。");
    }
    else if (Result.Projects.Num() == 0)
    {
        Result.Error = TEXT("commonSetting.json 的 DataBase 项目列表为空。");
    }
    return Result;
}

FString SCGToolsPublisherWindow::ReadPublisherName()
{
    const FString AppData = FPlatformMisc::GetEnvironmentVariable(TEXT("APPDATA"));
    if (AppData.IsEmpty())
    {
        return FString();
    }

    const FString SettingFile = AppData / TEXT("ShotManagerTemp/setting.json");
    FString JsonText;
    if (FFileHelper::LoadFileToString(JsonText, *SettingFile))
    {
        TSharedPtr<FJsonObject> Object;
        const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonText);
        if (FJsonSerializer::Deserialize(Reader, Object) && Object.IsValid())
        {
            FString User;
            if (Object->TryGetStringField(TEXT("user"), User) && !User.TrimStartAndEnd().IsEmpty())
            {
                return User.TrimStartAndEnd();
            }
        }
    }

    FConfigFile ConfigFile;
    ConfigFile.Read(AppData / TEXT("ShotManagerTemp/Configs/prefs.ini"));
    FString User;
    if (ConfigFile.GetString(TEXT("Info"), TEXT("user"), User))
    {
        return User.TrimStartAndEnd();
    }
    return FString();
}

bool SCGToolsPublisherWindow::IsSafePathComponent(const FString& Value, FString& OutReason)
{
    FString Trimmed = Value.TrimStartAndEnd();
    if (Trimmed.IsEmpty())
    {
        OutReason = TEXT("资产名不能为空。");
        return false;
    }
    if (Trimmed == TEXT(".") || Trimmed == TEXT(".."))
    {
        OutReason = TEXT("资产名不能是 . 或 ..。");
        return false;
    }
    if (Trimmed.EndsWith(TEXT(".")) || Trimmed.EndsWith(TEXT(" ")))
    {
        OutReason = TEXT("资产名不能以句点或空格结尾。");
        return false;
    }

    static const FString InvalidCharacters = TEXT("\\/:*?\"<>|");
    for (const TCHAR Character : InvalidCharacters)
    {
        if (Trimmed.Contains(FString::Chr(Character)))
        {
            OutReason = FString::Printf(TEXT("资产名包含非法路径字符：%c"), Character);
            return false;
        }
    }
    return true;
}

void SCGToolsPublisherWindow::RefreshTypes()
{
    TypeOptions.Reset();
    SelectedType.Reset();

    if (bSkeletalMeshPublish)
    {
        TypeOptions.Add(MakeShared<FString>(TEXT("Characters")));
        TypeOptions.Add(MakeShared<FString>(TEXT("Props")));
    }
    else if (Config.IsValid() && SelectedProject.IsValid())
    {
        TArray<FString> Directories;
        const FString ScenesPath = Config.RootPath / *SelectedProject / Config.ScenesFolder;
        IFileManager::Get().FindFiles(Directories, *(ScenesPath / TEXT("*")), false, true);
        Directories.Sort([](const FString& A, const FString& B)
        {
            return A.Compare(B, ESearchCase::IgnoreCase) < 0;
        });
        for (const FString& Directory : Directories)
        {
            TypeOptions.Add(MakeShared<FString>(Directory));
        }
    }

    if (!bSkeletalMeshPublish && SelectedProject.IsValid() && TypeOptions.IsEmpty())
    {
        TypeOptions.Add(MakeShared<FString>(TEXT("StaticMesh")));
    }

    if (TypeCombo.IsValid())
    {
        TypeCombo->ClearSelection();
        TypeCombo->RefreshOptions();
    }
    if (TypeTextBox.IsValid())
    {
        TypeTextBox->SetText(FText::GetEmpty());
    }
}

void SCGToolsPublisherWindow::RefreshTargetPath()
{
    if (!TargetPathText.IsValid())
    {
        return;
    }

    if (!Config.IsValid())
    {
        TargetPathText->SetText(FText::FromString(Config.Error));
        return;
    }

    if (GetSelectedProject().IsEmpty() || GetSelectedType().IsEmpty())
    {
        TargetPathText->SetText(LOCTEXT("ChoosePublishDestination", "请选择项目和类型。"));
        return;
    }

    const FString AssetRoot = GetAssetRoot();
    const FString AssetName = GetAssetName();
    TArray<FString> PublishedItems;
    PublishedItems.Add(TEXT("UE/Content/（整个资产文件夹及完整依赖）"));
    PublishedItems.Add(FString::Printf(TEXT("UE/%s.uproject"), *AssetName));
    if (PublishFbxCheckBox.IsValid() && PublishFbxCheckBox->IsChecked())
    {
        PublishedItems.Add(FString::Printf(TEXT("FBX/%s.fbx"), *AssetName));
    }
    if (PublishTextureCheckBox.IsValid() && PublishTextureCheckBox->IsChecked())
    {
        PublishedItems.Add(TEXT("Texture/（依赖贴图导出文件）"));
    }
    if (PublishIconCheckBox.IsValid() && PublishIconCheckBox->IsChecked())
    {
        PublishedItems.Add(FString::Printf(TEXT("Icon/%s.png"), *AssetName));
    }

    FString TargetDescription = AssetRoot + TEXT("\n");
    for (int32 Index = 0; Index < PublishedItems.Num(); ++Index)
    {
        TargetDescription += FString::Printf(
            TEXT("  %s─ %s%s"),
            Index == PublishedItems.Num() - 1 ? TEXT("└") : TEXT("├"),
            *PublishedItems[Index],
            Index == PublishedItems.Num() - 1 ? TEXT("") : TEXT("\n")
        );
    }
    TargetPathText->SetText(FText::FromString(TargetDescription));
}

bool SCGToolsPublisherWindow::IsSkeletalMeshPublish() const
{
    return bSkeletalMeshPublish;
}

FString SCGToolsPublisherWindow::GetPublishBaseFolder() const
{
    return bSkeletalMeshPublish ? Config.AssetsFolder : Config.ScenesFolder;
}

FString SCGToolsPublisherWindow::GetAssetKindLabel() const
{
    return bSkeletalMeshPublish ? TEXT("骨架网格体") : TEXT("静态网格体");
}

FString SCGToolsPublisherWindow::GetSelectedProject() const
{
    return SelectedProject.IsValid() ? *SelectedProject : FString();
}

FString SCGToolsPublisherWindow::GetSelectedType() const
{
    return TypeTextBox.IsValid()
        ? TypeTextBox->GetText().ToString().TrimStartAndEnd()
        : (SelectedType.IsValid() ? *SelectedType : FString());
}

bool SCGToolsPublisherWindow::ResolveMeshAssetFolder(FString& OutType, FString& OutName, FString& OutError)
{
    const FString PackageName = AssetData.PackageName.ToString();
    return bSkeletalMeshPublish
        ? CGToolsPublisher::ResolveSkeletalAssetFolder(PackageName, Config.AssetsFolder,
            OutType, MeshAssetFolder, OutName, OutError)
        : CGToolsPublisher::ResolveStaticAssetFolder(PackageName, Config.AssetsFolder, Config.ScenesFolder,
            OutType, MeshAssetFolder, OutName, OutError);
}

FString SCGToolsPublisherWindow::GetAssetName() const
{
    if (!MeshAssetFolder.IsEmpty())
    {
        return FPaths::GetCleanFilename(MeshAssetFolder);
    }
    return AssetNameTextBox.IsValid()
        ? AssetNameTextBox->GetText().ToString().TrimStartAndEnd()
        : AssetData.AssetName.ToString();
}

FString SCGToolsPublisherWindow::GetAssetRoot() const
{
    return Config.RootPath
        / GetSelectedProject()
        / GetPublishBaseFolder()
        / GetSelectedType()
        / GetAssetName();
}

TSharedRef<SWidget> SCGToolsPublisherWindow::GenerateComboItem(TSharedPtr<FString> Item) const
{
    return SNew(STextBlock).Text(FText::FromString(Item.IsValid() ? *Item : FString()));
}

FText SCGToolsPublisherWindow::GetProjectComboText() const
{
    return FText::FromString(GetSelectedProject());
}

FText SCGToolsPublisherWindow::GetTypeComboText() const
{
    return FText::FromString(GetSelectedType());
}

FText SCGToolsPublisherWindow::GetPublishBaseFolderPrefixText() const
{
    return FText::FromString(GetPublishBaseFolder() + TEXT("\\"));
}

void SCGToolsPublisherWindow::OnProjectChanged(
    TSharedPtr<FString> NewValue,
    ESelectInfo::Type SelectInfo
)
{
    if (SelectedProject != NewValue)
    {
        SelectedProject = NewValue;
        RefreshTypes();
        RefreshTargetPath();
    }
}

void SCGToolsPublisherWindow::OnTypeChanged(
    TSharedPtr<FString> NewValue,
    ESelectInfo::Type SelectInfo
)
{
    if (NewValue.IsValid())
    {
        SelectedType = NewValue;
        if (TypeTextBox.IsValid())
        {
            TypeTextBox->SetText(FText::FromString(*NewValue));
        }
        RefreshTargetPath();
    }
}

void SCGToolsPublisherWindow::OnTypeTextChanged(const FText& NewText)
{
    RefreshTargetPath();
}

void SCGToolsPublisherWindow::OnAssetNameChanged(const FText& NewText)
{
    RefreshTargetPath();
}

bool CGToolsPublisher::CaptureScreenshotPixels(
    TArray<FColor>& OutPixels, FIntPoint& OutSize,
    const TSharedPtr<SWindow>& ParentWindow, FText& OutError)
{
    OutPixels.Reset();
    OutSize = FIntPoint::ZeroValue;
    OutError = FText::GetEmpty();
    bool bAccepted = false;
    const auto ShowError = [](const FText& Message)
    {
        FMessageDialog::Open(EAppMsgType::Ok, Message, LOCTEXT("CaptureErrorTitle", "CGTools 截图"));
    };
    TArray<FColor> ScreenshotPixels;
    FIntPoint ScreenshotSize;
    FIntPoint DesktopOrigin;
    if (!CaptureVirtualDesktopPixels(
            ScreenshotPixels,
            ScreenshotSize,
            DesktopOrigin
        ))
    {
        OutError = LOCTEXT(
            "CaptureFailed",
            "无法读取 Windows 虚拟桌面画面。\n\n"
            "请确认显示器连接正常，然后重试。"
        );
        return false;
    }
    for (FColor& Pixel : ScreenshotPixels)
    {
        Pixel.A = 255;
    }

    const FVector2D DisplaySize(
        ScreenshotSize.X,
        ScreenshotSize.Y
    );

    const TSharedRef<SWindow> CaptureDialog = SNew(SWindow)
        .Type(EWindowType::Normal)
        .Title(LOCTEXT("CaptureDialogTitle", "CGTools 屏幕截图"))
        .AutoCenter(EAutoCenter::None)
        .ScreenPosition(FVector2D(DesktopOrigin.X, DesktopOrigin.Y))
        .ClientSize(DisplaySize)
        .AdjustInitialSizeAndPositionForDPIScale(false)
        .SizingRule(ESizingRule::FixedSize)
        .IsTopmostWindow(true)
        .FocusWhenFirstShown(true)
        .UseOSWindowBorder(false)
        .HasCloseButton(false)
        .CreateTitleBar(false)
        .SupportsMinimize(false)
        .SupportsMaximize(false)
        .SaneWindowPlacement(false)
        .LayoutBorder(FMargin(0.0f))
        .UserResizeBorder(FMargin(0.0f))
        .bManualManageDPI(true);

    TSharedPtr<SCGToolsScreenshotSelector> Selector;
    const TSharedRef<SWidget> CaptureContent =
        SNew(SConstraintCanvas)
        + SConstraintCanvas::Slot()
        .Anchors(FAnchors(0.0f, 0.0f, 1.0f, 1.0f))
        .Offset(FMargin(0.0f))
        .Alignment(FVector2D::ZeroVector)
        .ZOrder(0.0f)
        [
            SAssignNew(Selector, SCGToolsScreenshotSelector)
            .SourcePixels(ScreenshotPixels)
            .SourceSize(ScreenshotSize)
            .DisplaySize(DisplaySize)
        ]
        + SConstraintCanvas::Slot()
        .Anchors(FAnchors(0.0f))
        .Offset(FMargin(18.0f, 18.0f, 0.0f, 0.0f))
        .Alignment(FVector2D::ZeroVector)
        .AutoSize(true)
        .ZOrder(10.0f)
        [
            SNew(SBorder)
            .BorderImage(FAppStyle::GetBrush("ToolPanel.GroupBorder"))
            .Padding(FMargin(12.0f, 8.0f))
            [
                SNew(STextBlock)
                .Text(LOCTEXT(
                    "CaptureInstructions",
                    "拖动框选；拖内部移动；拖绿色手柄缩放；右键清除；双击框内确定；Esc 退出。"
                ))
            ]
        ]
        + SConstraintCanvas::Slot()
        .Anchors(FAnchors(0.0f))
        .Offset(TAttribute<FMargin>::CreateLambda([Selector]()
        {
            constexpr float ToolbarWidth = 292.0f;
            constexpr float ToolbarHeight = 44.0f;
            const FVector2D Position = Selector.IsValid()
                ? Selector->GetToolbarPosition(ToolbarWidth, ToolbarHeight)
                : FVector2D::ZeroVector;
            return FMargin(Position.X, Position.Y, 0.0f, 0.0f);
        }))
        .Alignment(FVector2D::ZeroVector)
        .AutoSize(true)
        .ZOrder(20.0f)
        [
            SNew(SBox)
            .WidthOverride(292.0f)
            .HeightOverride(44.0f)
            .Visibility_Lambda([Selector]()
            {
                return Selector.IsValid() && Selector->HasValidSelection()
                    ? EVisibility::Visible
                    : EVisibility::Collapsed;
            })
            [
                SNew(SBorder)
                .BorderImage(FAppStyle::GetBrush("ToolPanel.GroupBorder"))
                .Padding(6.0f)
                [
                    SNew(SHorizontalBox)
                    + SHorizontalBox::Slot()
                    .FillWidth(1.0f)
                    [
                        SNew(SButton)
                            .Text(LOCTEXT("SaveCapture", "保存"))
                            .ToolTipText(LOCTEXT("SaveCaptureTooltip", "将当前选区另存为 PNG"))
                            .OnClicked_Lambda([ShowError, Selector, CaptureDialog]()
                            {
                                TArray<FColor> SelectedPixels;
                                FIntPoint SelectedSize;
                                if (!Selector.IsValid()
                                    || !Selector->GetSelectedPixels(SelectedPixels, SelectedSize))
                                {
                                    ShowError(LOCTEXT("InvalidSaveSelection", "请先框选有效的截图区域。"));
                                    return FReply::Handled();
                                }

                                IDesktopPlatform* DesktopPlatform =
                                    FDesktopPlatformModule::Get();
                                if (!DesktopPlatform)
                                {
                                    ShowError(LOCTEXT("DesktopPlatformMissing", "无法打开保存文件对话框。"));
                                    return FReply::Handled();
                                }

                                void* ParentWindowHandle = nullptr;
                                if (const TSharedPtr<FGenericWindow> NativeWindow =
                                        CaptureDialog->GetNativeWindow())
                                {
                                    ParentWindowHandle = NativeWindow->GetOSWindowHandle();
                                }

                                TArray<FString> SaveFilenames;
                                if (!DesktopPlatform->SaveFileDialog(
                                        ParentWindowHandle,
                                        LOCTEXT("SaveCaptureDialogTitle", "保存截图").ToString(),
                                        FPaths::ProjectSavedDir(),
                                        TEXT("CGToolsScreenshot.png"),
                                        TEXT("PNG 图片 (*.png)|*.png"),
                                        EFileDialogFlags::None,
                                        SaveFilenames
                                    )
                                    || SaveFilenames.Num() == 0)
                                {
                                    return FReply::Handled();
                                }

                                FString SaveFilename = SaveFilenames[0];
                                if (!SaveFilename.EndsWith(TEXT(".png"), ESearchCase::IgnoreCase))
                                {
                                    SaveFilename += TEXT(".png");
                                }
                                TArray64<uint8> CompressedPng;
                                FImageUtils::PNGCompressImageArray(
                                    SelectedSize.X,
                                    SelectedSize.Y,
                                    TArrayView64<const FColor>(
                                        SelectedPixels.GetData(),
                                        static_cast<int64>(SelectedPixels.Num())
                                    ),
                                    CompressedPng
                                );
                                if (CompressedPng.Num() == 0
                                    || !FFileHelper::SaveArrayToFile(
                                        CompressedPng,
                                        *SaveFilename
                                    ))
                                {
                                    ShowError(FText::Format(
                                        LOCTEXT("SaveCaptureFailed", "截图保存失败：\n{0}"),
                                        FText::FromString(SaveFilename)
                                    ));
                                }
                                return FReply::Handled();
                            })
                    ]
                    + SHorizontalBox::Slot()
                    .FillWidth(1.0f)
                    .Padding(4.0f, 0.0f, 0.0f, 0.0f)
                    [
                        SNew(SButton)
                        .Text(LOCTEXT("CopyCapture", "复制"))
                        .ToolTipText(LOCTEXT("CopyCaptureTooltip", "将当前选区复制到 Windows 剪贴板"))
                        .OnClicked_Lambda([ShowError, Selector, CaptureDialog]()
                        {
                            TArray<FColor> SelectedPixels;
                            FIntPoint SelectedSize;
                            if (!Selector.IsValid()
                                || !Selector->GetSelectedPixels(SelectedPixels, SelectedSize))
                            {
                                ShowError(LOCTEXT("InvalidCopySelection", "请先框选有效的截图区域。"));
                                return FReply::Handled();
                            }

                            void* OwnerWindowHandle = nullptr;
                            if (const TSharedPtr<FGenericWindow> NativeWindow =
                                    CaptureDialog->GetNativeWindow())
                            {
                                OwnerWindowHandle = NativeWindow->GetOSWindowHandle();
                            }
                            if (!CopyPixelsToClipboard(
                                    SelectedPixels,
                                    SelectedSize,
                                    OwnerWindowHandle
                                ))
                            {
                                ShowError(LOCTEXT("CopyCaptureFailed", "无法将截图写入 Windows 剪贴板。"));
                            }
                            return FReply::Handled();
                        })
                    ]
                    + SHorizontalBox::Slot()
                    .FillWidth(1.0f)
                    .Padding(4.0f, 0.0f, 0.0f, 0.0f)
                    [
                        SNew(SButton)
                        .ButtonStyle(FAppStyle::Get(), "PrimaryButton")
                        .Text(LOCTEXT("AcceptCapture", "确定"))
                        .OnClicked_Lambda([Selector]()
                        {
                            return Selector->AcceptSelection();
                        })
                    ]
                    + SHorizontalBox::Slot()
                    .FillWidth(1.0f)
                    .Padding(4.0f, 0.0f, 0.0f, 0.0f)
                    [
                        SNew(SButton)
                        .Text(LOCTEXT("CancelCapture", "取消"))
                        .OnClicked_Lambda([CaptureDialog]()
                        {
                            CaptureDialog->RequestDestroyWindow();
                            return FReply::Handled();
                        })
                    ]
                ]
            ]
        ];

    const TSharedRef<SCGToolsScreenshotOverlay> CaptureOverlay =
        SNew(SCGToolsScreenshotOverlay)[CaptureContent];
    CaptureDialog->SetContent(CaptureOverlay);
    CaptureDialog->SetWidgetToFocusOnActivate(CaptureOverlay);

    const TWeakPtr<SCGToolsScreenshotSelector> WeakSelector = Selector;
    const TWeakPtr<SWindow> WeakCaptureDialog = CaptureDialog;
    Selector->SetOnSelectionAccepted(FOnClicked::CreateLambda(
        [ShowError, WeakSelector, WeakCaptureDialog, &OutPixels, &OutSize, &bAccepted]()
        {
            const TSharedPtr<SCGToolsScreenshotSelector> PinnedSelector = WeakSelector.Pin();
            const TSharedPtr<SWindow> PinnedDialog = WeakCaptureDialog.Pin();
            TArray<FColor> SelectedPixels;
            FIntPoint SelectedSize;
            if (!PinnedSelector.IsValid()
                || !PinnedDialog.IsValid()
                || !PinnedSelector->GetSelectedPixels(SelectedPixels, SelectedSize))
            {
                ShowError(LOCTEXT("InvalidCaptureSelection", "请先框选有效的截图区域。"));
                return FReply::Handled();
            }
            OutPixels = MoveTemp(SelectedPixels);
            OutSize = SelectedSize;
            bAccepted = true;
            PinnedDialog->RequestDestroyWindow();
            return FReply::Handled().ReleaseMouseCapture();
        }
    ));

    FSlateApplication::Get().AddModalWindow(
        CaptureDialog,
        ParentWindow,
        false
    );
    Selector->SetOnSelectionAccepted(FOnClicked());
    // Toolbar delegates reference the dialog. Release its content to break that cycle.
    CaptureDialog->SetContent(SNullWidget::NullWidget);
    return bAccepted;
}

FReply SCGToolsPublisherWindow::OnCaptureIconClicked()
{
    TArray<FColor> Pixels;
    FIntPoint Size;
    FText Error;
    if (CGToolsPublisher::CaptureScreenshotPixels(
            Pixels, Size, FSlateApplication::Get().FindWidgetWindow(AsShared()), Error))
    {
        ApplyCapturedIcon(MoveTemp(Pixels), Size);
    }
    else if (!Error.IsEmpty())
    {
        ShowError(Error);
    }
    return FReply::Handled();
}

FReply SCGToolsPublisherWindow::OnUseAssetThumbnailClicked()
{
    CustomIconBrush.Reset();
    CustomIconPixels.Reset();
    CustomIconSize = FIntPoint::ZeroValue;
    Invalidate(EInvalidateWidgetReason::LayoutAndVolatility);
    return FReply::Handled();
}

void SCGToolsPublisherWindow::ApplyCapturedIcon(TArray<FColor> Pixels, FIntPoint Size)
{
    if (Size.X <= 0 || Size.Y <= 0 || Pixels.Num() != Size.X * Size.Y)
    {
        ShowError(LOCTEXT("CapturedIconInvalid", "截图数据无效，未替换当前 Icon。"));
        return;
    }
    for (FColor& Pixel : Pixels)
    {
        Pixel.A = 255;
    }

    TSharedPtr<FDeferredCleanupSlateBrush> NewBrush = CreatePreviewBrush(
        Pixels,
        Size,
        TEXT("CGToolsPublisher_CustomIcon")
    );
    if (!NewBrush.IsValid())
    {
        ShowError(LOCTEXT("CapturedIconPreviewFailed", "截图成功，但 UE 无法建立 Icon 预览纹理。"));
        return;
    }

    CustomIconBrush = MoveTemp(NewBrush);
    CustomIconPixels = MoveTemp(Pixels);
    CustomIconSize = Size;
    if (PublishIconCheckBox.IsValid())
    {
        PublishIconCheckBox->SetIsChecked(ECheckBoxState::Checked);
    }
    Invalidate(EInvalidateWidgetReason::LayoutAndVolatility);
}

void SCGToolsPublisherWindow::BuildAutomaticIcon(UObject* Asset)
{
    AutomaticIconBrush.Reset();
    AutomaticIconPixels.Reset();
    AutomaticIconSize = FIntPoint::ZeroValue;
    if (!Asset)
    {
        return;
    }

    FObjectThumbnail Thumbnail;
    bool bHasThumbnail =
        ThumbnailTools::LoadThumbnailFromPackage(AssetData, Thumbnail)
        && !Thumbnail.IsEmpty();
    if (bHasThumbnail)
    {
        const TArray<uint8>& SavedPixels = Thumbnail.GetUncompressedImageData();
        bHasThumbnail =
            Thumbnail.GetImageWidth() > 0
            && Thumbnail.GetImageHeight() > 0
            && SavedPixels.Num()
                == Thumbnail.GetImageWidth() * Thumbnail.GetImageHeight() * 4;
        if (bHasThumbnail)
        {
            bool bHasVisiblePixel = false;
            for (int32 Index = 0; Index + 3 < SavedPixels.Num(); Index += 4)
            {
                if (SavedPixels[Index] > 4
                    || SavedPixels[Index + 1] > 4
                    || SavedPixels[Index + 2] > 4)
                {
                    bHasVisiblePixel = true;
                    break;
                }
            }
            bHasThumbnail = bHasVisiblePixel;
        }
    }
    if (!bHasThumbnail)
    {
        constexpr int32 PreviewSize = 512;
        ThumbnailTools::RenderThumbnail(
            Asset,
            PreviewSize,
            PreviewSize,
            ThumbnailTools::EThumbnailTextureFlushMode::AlwaysFlush,
            nullptr,
            &Thumbnail
        );
    }

    const int32 Width = Thumbnail.GetImageWidth();
    const int32 Height = Thumbnail.GetImageHeight();
    const TArray<uint8>& ImageData = Thumbnail.GetUncompressedImageData();
    if (Width <= 0 || Height <= 0 || ImageData.Num() != Width * Height * 4)
    {
        return;
    }

    AutomaticIconPixels.SetNumUninitialized(Width * Height);
    FMemory::Memcpy(
        AutomaticIconPixels.GetData(),
        ImageData.GetData(),
        ImageData.Num()
    );
    for (FColor& Pixel : AutomaticIconPixels)
    {
        Pixel.A = 255;
    }
    AutomaticIconSize = FIntPoint(Width, Height);
    AutomaticIconBrush = CreatePreviewBrush(
        AutomaticIconPixels,
        AutomaticIconSize,
        TEXT("CGToolsPublisher_AssetThumbnail")
    );
}

const FSlateBrush* SCGToolsPublisherWindow::GetAutomaticIconBrush() const
{
    return AutomaticIconBrush.IsValid()
        ? AutomaticIconBrush->GetSlateBrush()
        : FAppStyle::GetBrush("NoBrush");
}

const FSlateBrush* SCGToolsPublisherWindow::GetCustomIconBrush() const
{
    return CustomIconBrush.IsValid()
        ? CustomIconBrush->GetSlateBrush()
        : FAppStyle::GetBrush("NoBrush");
}

FReply SCGToolsPublisherWindow::OnPublishClicked()
{
    if (bIsPublishing)
    {
        return FReply::Handled();
    }

    UObject* Asset = PublishAsset.Get();
    if (!Asset)
    {
        ShowError(FText::FromString(FString::Printf(
            TEXT("所选%s已经失效，请关闭窗口后重新选择资产。"),
            *GetAssetKindLabel()
        )));
        return FReply::Handled();
    }
    if (!Config.IsValid())
    {
        ShowError(FText::FromString(Config.Error));
        return FReply::Handled();
    }

    FString InvalidReason;
    const FString AssetName = GetAssetName();
    if (!IsSafePathComponent(AssetName, InvalidReason))
    {
        ShowError(FText::FromString(InvalidReason));
        return FReply::Handled();
    }

    const FString Project = GetSelectedProject();
    const FString AssetType = GetSelectedType();
    if (Project.IsEmpty() || AssetType.IsEmpty())
    {
        ShowError(LOCTEXT("MissingProjectOrType", "请选择项目和资产类型。"));
        return FReply::Handled();
    }
    FString InvalidTypeReason;
    if (!IsSafePathComponent(AssetType, InvalidTypeReason))
    {
        InvalidTypeReason.ReplaceInline(TEXT("资产名"), TEXT("类型"));
        ShowError(FText::FromString(InvalidTypeReason));
        return FReply::Handled();
    }

    const FString PackageName = AssetData.PackageName.ToString();
    if (!PackageName.StartsWith(TEXT("/Game/")))
    {
        ShowError(FText::Format(
            LOCTEXT(
                "NotGameAsset",
                "当前版本只发布当前工程 /Game 下的网格体。\n\n所选包：{0}"
            ),
            FText::FromString(PackageName)
        ));
        return FReply::Handled();
    }

    FString FolderType, FolderName, FolderError;
    if (!ResolveMeshAssetFolder(FolderType, FolderName, FolderError))
    {
        ShowError(FText::FromString(FolderError));
        return FReply::Handled();
    }
    if (bSkeletalMeshPublish && !FolderType.Equals(AssetType, ESearchCase::IgnoreCase))
    {
        ShowError(FText::FromString(FString::Printf(
            TEXT("所选类型与资产文件夹不一致。\n\n资产目录：%s\n请选择类型：%s"),
            *MeshAssetFolder, *FolderType)));
        return FReply::Handled();
    }

    TGuardValue<bool> DialogPublishingGuard(DialogState->bPublishing, true);
    bIsPublishing = true;
    SetProgress(0.03f, LOCTEXT("CheckingDatabase", "正在检查数据库记录…"));

    FCGToolsDatabaseResult DatabaseCheck;
    {
        FScopedSlowTask DatabaseProgress(
            1.0f,
            LOCTEXT("CheckingDatabaseSlowTask", "正在检查发布数据库…")
        );
        DatabaseProgress.MakeDialog(false, false);
        DatabaseProgress.EnterProgressFrame(
            1.0f,
            LOCTEXT("CheckingDatabaseSlowTaskFrame", "正在检查同名资产记录…")
        );
        DatabaseCheck = bSkeletalMeshPublish
            ? FCGToolsPublisherDatabase::CheckAssetRecord(
                Project, AssetName, Config.Host)
            : FCGToolsPublisherDatabase::CheckSceneRecord(
                Project, AssetName, Config.Host);
    }
    if (!DatabaseCheck.bOk)
    {
        bIsPublishing = false;
        SetProgress(0.0f, LOCTEXT("DatabaseCheckFailedStatus", "数据库检查失败"));
        ShowError(FText::Format(
            LOCTEXT("DatabaseCheckFailed", "无法检查发布数据库：\n\n{0}"),
            FText::FromString(DatabaseCheck.Error)
        ));
        return FReply::Handled();
    }

    if (DatabaseCheck.bExists && !DialogState->bBatchExecution)
    {
        const FString OverwriteMessage = FString::Printf(
            TEXT("数据库中已存在同名资产。\n\n")
            TEXT("项目数据库：%s\n")
            TEXT("资产名：%s\n")
            TEXT("发布类型：%s\n\n")
            TEXT("数据库表：public.%s\n\n")
            TEXT("继续操作将覆盖该资产的数据库发布记录；若服务器上已有旧发布文件，提交前会备份到 history。\n\n")
            TEXT("是否确认覆盖并继续？"),
            *Project,
            *AssetName,
            *AssetType,
            bSkeletalMeshPublish ? TEXT("asset") : TEXT("scene")
        );
        if (FMessageDialog::Open(
                EAppMsgType::YesNo,
                FText::FromString(OverwriteMessage),
                LOCTEXT("DatabaseAssetExistsTitle", "同名资产已存在 - 确认覆盖")
            ) != EAppReturnType::Yes)
        {
            bIsPublishing = false;
            SetProgress(0.0f, LOCTEXT("OverwriteCancelled", "已取消覆盖发布"));
            return FReply::Handled();
        }
    }

    const bool bPublishFbx = PublishFbxCheckBox.IsValid()
        && PublishFbxCheckBox->IsChecked();
    const bool bPublishIcon = PublishIconCheckBox.IsValid()
        && PublishIconCheckBox->IsChecked();
    const bool bPublishTextures = PublishTextureCheckBox.IsValid()
        && PublishTextureCheckBox->IsChecked();
    const FString AssetRoot = GetAssetRoot();
    const FString FinalContent = AssetRoot / TEXT("UE/Content");
    const FString FinalProjectFile = AssetRoot / TEXT("UE") / (AssetName + TEXT(".uproject"));
    const FString FinalFbxFile = AssetRoot / TEXT("FBX") / (AssetName + TEXT(".fbx"));
    const FString FinalIconFile = AssetRoot / TEXT("Icon") / (AssetName + TEXT(".png"));
    const FString FinalTextureDirectory = AssetRoot / TEXT("Texture");

    IPlatformFile& PlatformFile = FPlatformFileManager::Get().GetPlatformFile();
    const bool bPublishedFilesExist =
        PlatformFile.DirectoryExists(*FinalContent)
        || PlatformFile.FileExists(*FinalProjectFile)
        || (bPublishFbx && PlatformFile.FileExists(*FinalFbxFile))
        || (bPublishIcon && PlatformFile.FileExists(*FinalIconFile))
        || (bPublishTextures && PlatformFile.DirectoryExists(*FinalTextureDirectory));

    FString Confirmation = FString::Printf(
        TEXT("即将发布%s：%s\n\n项目：%s\n类型：%s\\%s\n目标：%s\n\n")
        TEXT("UE 资产将使用原生迁移，自动带齐材质、贴图及其他包依赖。\n")
        TEXT("发布 FBX：%s\n发布 Icon：%s\n发布 Texture：%s\n"),
        *GetAssetKindLabel(),
        *AssetName,
        *Project,
        *GetPublishBaseFolder(),
        *AssetType,
        *AssetRoot,
        bPublishFbx ? TEXT("是") : TEXT("否"),
        bPublishIcon ? TEXT("是") : TEXT("否"),
        bPublishTextures ? TEXT("是") : TEXT("否")
    );
    Confirmation += FString::Printf(
        TEXT("\nUE 发布范围：%s 下的全部资源及依赖。\nFBX 和 Icon 使用当前选中的模型：%s。\n"),
        *MeshAssetFolder, *AssetData.AssetName.ToString());
    if (bPublishedFilesExist)
    {
        Confirmation += TEXT(
            "\n警告：服务器上已有发布文件；确认后会先备份旧文件，"
            "再覆盖当前发布内容。\n"
        );
    }
    Confirmation += TEXT("\n是否继续？");

    if (!DialogState->bBatchExecution && FMessageDialog::Open(
            EAppMsgType::YesNo,
            FText::FromString(Confirmation),
            LOCTEXT("PublishConfirmTitle", "发布 UE 资产")
        ) != EAppReturnType::Yes)
    {
        bIsPublishing = false;
        SetProgress(0.0f, LOCTEXT("Cancelled", "已取消发布"));
        return FReply::Handled();
    }

    TUniquePtr<FScopedSlowTask> PublishSlowTask = MakeUnique<FScopedSlowTask>(
        1.0f,
        LOCTEXT("PublishingSlowTask", "正在发布 UE 资产…")
    );
    PublishSlowTask->MakeDialog(false, false);
    float SlowTaskProgress = 0.0f;
    auto UpdatePublishProgress = [this, &PublishSlowTask, &SlowTaskProgress](
        float NewProgress,
        const FText& NewStatus)
    {
        const float ClampedProgress = FMath::Clamp(NewProgress, 0.0f, 1.0f);
        SetProgress(ClampedProgress, NewStatus);
        if (PublishSlowTask.IsValid())
        {
            const float ProgressDelta = FMath::Max(
                0.0f,
                ClampedProgress - SlowTaskProgress
            );
            PublishSlowTask->EnterProgressFrame(ProgressDelta, NewStatus);
            PublishSlowTask->ForceRefresh();
        }
        SlowTaskProgress = FMath::Max(SlowTaskProgress, ClampedProgress);
    };
    UpdatePublishProgress(
        0.06f,
        LOCTEXT("PreparingStaging", "正在建立本地发布暂存目录…")
    );

    const FString StagingRoot = FPaths::ProjectSavedDir()
        / TEXT("CGToolsPublisher/Staging")
        / FGuid::NewGuid().ToString(EGuidFormats::Digits);
    const FString StagedContent = StagingRoot / TEXT("UE/Content");
    const FString StagedProjectFile =
        StagingRoot / TEXT("UE") / (AssetName + TEXT(".uproject"));
    const FString StagedTextureDirectory = StagingRoot / TEXT("Texture");
    const FString RelativeAssetFile = PackageName.Mid(6) + TEXT(".uasset");

    FString Error;
    TArray<FName> PackagesToMigrate;
    PackagesToMigrate.Add(AssetData.PackageName);
    int32 PublishedTextureCount = 0;
    PlatformFile.CreateDirectoryTree(*StagedContent);
    bool bSucceeded = PlatformFile.DirectoryExists(*StagedContent);
    if (!bSucceeded)
    {
        Error = FString::Printf(TEXT("无法建立发布暂存目录：%s"), *StagedContent);
    }

    if (bSucceeded && (bPublishFbx || bPublishIcon))
    {
        UpdatePublishProgress(0.14f, LOCTEXT("ExportingMeshOutputs", "正在导出所选模型的 FBX / Icon…"));
        bSucceeded = ExportMeshOutputs(StagingRoot, bPublishFbx, bPublishIcon, Error);
    }

    if (bSucceeded)
    {
        UpdatePublishProgress(0.34f, LOCTEXT("WritingProject", "正在生成 .uproject…"));
        PlatformFile.CreateDirectoryTree(*FPaths::GetPath(StagedProjectFile));
        bSucceeded = WriteProjectFile(StagedProjectFile, Error);
    }

    if (bSucceeded)
    {
        UpdatePublishProgress(0.42f, LOCTEXT("MigratingAssets", "正在迁移 .uasset 及完整依赖…"));
        FAssetRegistryModule& AssetRegistryModule =
            FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
        AssetRegistryModule.Get().WaitForCompletion();

        FMigrationOptions MigrationOptions;
        MigrationOptions.bPrompt = false;
        MigrationOptions.bIgnoreDependencies = false;
        MigrationOptions.AssetConflict = EAssetMigrationConflict::Overwrite;

        TArray<FAssetData> FolderAssets;
        AssetRegistryModule.Get().GetAssetsByPath(
            FName(*MeshAssetFolder), FolderAssets, true);
        CGToolsPublisher::AddAssetFolderPackages(
            MeshAssetFolder, FolderAssets, PackagesToMigrate);
        PackagesToMigrate.Sort(FNameLexicalLess());
        FModuleManager::LoadModuleChecked<FAssetToolsModule>(TEXT("AssetTools"))
            .Get()
            .MigratePackages(PackagesToMigrate, StagedContent, MigrationOptions);

        // Native migration can temporarily remove the source packages from
        // the Content Browser even though their files still exist on disk.
        // Run the same recovery used by AssetRegistryRepair's context-menu
        // command, scoped to the published asset's source folder.
        UpdatePublishProgress(0.58f, LOCTEXT(
            "RepairingSourceAssetDisplay",
            "正在修复当前工程资产显示…"
        ));
        TArray<FString> RepairFolders;
        RepairFolders.Add(MeshAssetFolder);
        FString RepairMessage;
        if (!CGToolsPublisher::RepairSourceAssetDisplay(RepairFolders, RepairMessage))
        {
            UE_LOG(
                LogCGToolsPublisher,
                Warning,
                TEXT("发布迁移完成，但自动修复源资产显示失败：%s"),
                *RepairMessage
            );
        }

        const FString ExpectedStagedAsset = StagedContent / RelativeAssetFile;
        if (!PlatformFile.FileExists(*ExpectedStagedAsset))
        {
            bSucceeded = false;
            Error = FString::Printf(
                TEXT("UE 迁移结束后未找到主资产：%s\n迁移可能被取消，或源包不属于 /Game。"),
                *ExpectedStagedAsset
            );
        }
        if (bSucceeded)
        {
            for (FName FolderPackage : PackagesToMigrate)
            {
                const FString RelativePackage = FolderPackage.ToString().Mid(6);
                if (!PlatformFile.FileExists(*(StagedContent / (RelativePackage + TEXT(".uasset"))))
                    && !PlatformFile.FileExists(*(StagedContent / (RelativePackage + TEXT(".umap")))))
                {
                    bSucceeded = false;
                    Error = FString::Printf(TEXT("资产文件夹迁移不完整，缺少包：%s"), *FolderPackage.ToString());
                    break;
                }
            }
        }
    }

    if (bSucceeded && bPublishTextures)
    {
        UpdatePublishProgress(0.66f, LOCTEXT("ExportingTextures", "正在导出依赖贴图…"));
        bSucceeded = ExportReferencedTextures(
            PackagesToMigrate,
            StagedTextureDirectory,
            PublishedTextureCount,
            Error
        );
    }

    FString HistoryPath;
    if (bSucceeded)
    {
        UpdatePublishProgress(0.76f, LOCTEXT("PromotingPublish", "正在备份旧版本并上传服务器…"));
        struct FAsyncPromotionResult
        {
            bool bSucceeded = false;
            FString HistoryPath;
            FString Error;
        };

        TFuture<FAsyncPromotionResult> PromotionFuture = Async(
            EAsyncExecution::ThreadPool,
            [
                AssetName,
                AssetRoot,
                StagingRoot,
                RelativeAssetFile,
                bPublishFbx,
                bPublishIcon,
                bPublishTextures
            ]()
            {
                FAsyncPromotionResult Result;
                Result.bSucceeded = PromoteStagedPublish(
                    AssetName,
                    AssetRoot,
                    StagingRoot,
                    RelativeAssetFile,
                    bPublishFbx,
                    bPublishIcon,
                    bPublishTextures,
                    Result.HistoryPath,
                    Result.Error
                );
                return Result;
            }
        );

        while (!PromotionFuture.IsReady())
        {
            PublishSlowTask->TickProgress();
            FPlatformProcess::Sleep(0.03f);
        }
        FAsyncPromotionResult PromotionResult = PromotionFuture.Get();
        bSucceeded = PromotionResult.bSucceeded;
        HistoryPath = MoveTemp(PromotionResult.HistoryPath);
        Error = MoveTemp(PromotionResult.Error);
    }

    PlatformFile.DeleteDirectoryRecursively(*StagingRoot);

    if (!bSucceeded)
    {
        PublishSlowTask.Reset();
        bIsPublishing = false;
        SetProgress(0.0f, LOCTEXT("PublishFailedStatus", "发布失败"));
        ShowError(FText::Format(
            LOCTEXT("PublishFailed", "发布 UE 资产失败：\n\n{0}"),
            FText::FromString(Error)
        ));
        return FReply::Handled();
    }

    UpdatePublishProgress(0.90f, LOCTEXT("WritingDatabase", "文件已上传，正在写入数据库…"));
    const FString ChineseName = ChineseNameTextBox.IsValid()
        ? ChineseNameTextBox->GetText().ToString().TrimStartAndEnd()
        : FString();
    const FString IconDatabasePath = FinalIconFile.Replace(TEXT("\\"), TEXT("/"));
    const FCGToolsDatabaseResult DatabaseWrite = bSkeletalMeshPublish
        ? FCGToolsPublisherDatabase::WriteAssetRecord(
            Project,
            AssetName,
            ChineseName,
            AssetType,
            IconDatabasePath,
            Config.Host,
            DatabaseCheck.bExists
        )
        : FCGToolsPublisherDatabase::WriteSceneRecord(
            Project,
            AssetName,
            ChineseName,
            AssetType,
            IconDatabasePath,
            Config.Host,
            DatabaseCheck.bExists
        );

    if (!DatabaseWrite.bOk)
    {
        UpdatePublishProgress(
            0.94f,
            LOCTEXT("DatabaseWriteFailedStatus", "文件发布完成，但数据库写入失败")
        );
        PublishSlowTask.Reset();
        bIsPublishing = false;
        SetProgress(0.94f, LOCTEXT("DatabaseWriteFailedStatus", "文件发布完成，但数据库写入失败"));
        ShowError(FText::Format(
            LOCTEXT(
                "DatabaseWriteFailed",
                "服务器文件已经发布，但数据库记录写入失败。\n"
                "请不要手动删除发布文件；修复数据库登录或网络后重新执行发布即可。\n\n"
                "目标：{0}\n错误：{1}"
            ),
            FText::FromString(AssetRoot),
            FText::FromString(DatabaseWrite.Error)
        ));
        return FReply::Handled();
    }

    UpdatePublishProgress(1.0f, LOCTEXT("PublishCompleteStatus", "发布完成"));
    PublishSlowTask.Reset();
    bIsPublishing = false;
    SetProgress(1.0f, LOCTEXT("PublishCompleteStatus", "发布完成"));
    UE_LOG(
        LogCGToolsPublisher,
        Display,
        TEXT("Published %s %s to %s"),
        bSkeletalMeshPublish ? TEXT("skeletal mesh") : TEXT("static mesh"),
        *PackageName,
        *AssetRoot
    );

    FString SuccessMessage = FString::Printf(
        TEXT("%s发布完成。\n\nUE 内容：%s\n项目文件：%s\n数据库：public.%s (%s / %s)"),
        *GetAssetKindLabel(),
        *FinalContent,
        *FinalProjectFile,
        bSkeletalMeshPublish ? TEXT("asset") : TEXT("scene"),
        *Project,
        *AssetName
    );
    if (bPublishTextures)
    {
        SuccessMessage += FString::Printf(
            TEXT("\nTexture：%s（%d 个贴图资产）"),
            *FinalTextureDirectory,
            PublishedTextureCount
        );
    }
    if (!HistoryPath.IsEmpty())
    {
        SuccessMessage += FString::Printf(TEXT("\n旧版本备份：%s"), *HistoryPath);
    }
    DialogState->Completion = SuccessMessage;
    if (!DialogState->bBatchExecution)
    {
        FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(SuccessMessage), LOCTEXT("PublishCompleteTitle", "发布完成"));
    }
    DialogState->Result = ECGToolsPublisherDialogResult::Published;
    CloseWindow();
    return FReply::Handled();
}

FReply SCGToolsPublisherWindow::OnCancelClicked()
{
    if (!bIsPublishing)
    {
        CloseWindow();
    }
    return FReply::Handled();
}

FReply SCGToolsPublisherWindow::OnSkipClicked()
{
    if (!bIsPublishing && DialogState->IsBatch())
    {
        DialogState->Result = ECGToolsPublisherDialogResult::Skipped;
        CloseWindow();
    }
    return FReply::Handled();
}

bool SCGToolsPublisherWindow::CanPublish() const
{
    return !bIsPublishing
        && Config.IsValid()
        && PublishAsset.IsValid()
        && !GetSelectedProject().IsEmpty()
        && !GetSelectedType().IsEmpty()
        && !GetAssetName().IsEmpty();
}

void SCGToolsPublisherWindow::CloseWindow()
{
    if (DialogState->bEmbedded) { return; }
    const TSharedPtr<SWindow> Window = FSlateApplication::Get().FindWidgetWindow(AsShared());
    if (Window.IsValid())
    {
        FSlateApplication::Get().RequestDestroyWindow(Window.ToSharedRef());
    }
}

void SCGToolsPublisherWindow::SetProgress(float InProgress, const FText& InStatus)
{
    Progress = FMath::Clamp(InProgress, 0.0f, 1.0f);
    if (StatusText.IsValid())
    {
        StatusText->SetText(InStatus);
    }
    if (ProgressBar.IsValid())
    {
        ProgressBar->Invalidate(EInvalidateWidgetReason::Paint);
    }
}

void SCGToolsPublisherWindow::ShowError(const FText& Message) const
{
    DialogState->Error = Message.ToString();
    if (DialogState->bBatchExecution) { return; }
    FMessageDialog::Open(EAppMsgType::Ok, Message, LOCTEXT("ErrorTitle", "CGTools Publisher"));
}

FCGToolsPublisherSharedSettings SCGToolsPublisherWindow::GetSharedSettings() const
{
    FCGToolsPublisherSharedSettings Settings;
    Settings.Project = GetSelectedProject();
    Settings.Type = GetSelectedType();
    Settings.bIcon = PublishIconCheckBox->IsChecked();
    Settings.bFbx = PublishFbxCheckBox->IsChecked();
    Settings.bTextures = PublishTextureCheckBox->IsChecked();
    return Settings;
}

FString SCGToolsPublisherWindow::GetRecordLabel() const
{
    return ChineseNameTextBox->GetText().ToString();
}

void SCGToolsPublisherWindow::SetRecordLabel(const FString& Label)
{
    ChineseNameTextBox->SetText(FText::FromString(Label));
}

FString SCGToolsPublisherWindow::GetPerAssetSettingsKey() const
{
    const uint32 CaptureHash = CustomIconPixels.IsEmpty() ? 0
        : FCrc::MemCrc32(CustomIconPixels.GetData(), CustomIconPixels.Num() * sizeof(FColor));
    return FString::Printf(TEXT("%d:%d:%u:"), CustomIconSize.X, CustomIconSize.Y, CaptureHash) + GetRecordLabel();
}

void SCGToolsPublisherWindow::SetGroupPanels(const TArray<TSharedPtr<ICGToolsPublisherPanel>>& Panels)
{
    BatchMeshPanels.Reset();
    for (const TSharedPtr<ICGToolsPublisherPanel>& Panel : Panels)
    { BatchMeshPanels.Add(StaticCastSharedPtr<SCGToolsPublisherWindow>(Panel)); }
}

void SCGToolsPublisherWindow::ApplySharedSettings(const FCGToolsPublisherSharedSettings& Settings)
{
    if (GetSelectedProject() != Settings.Project)
    {
        const TSharedPtr<FString>* Project = ProjectOptions.FindByPredicate(
            [&Settings](const TSharedPtr<FString>& Item) { return *Item == Settings.Project; });
        ProjectCombo->SetSelectedItem(Project ? *Project : nullptr);
    }
    const TSharedPtr<FString>* Type = TypeOptions.FindByPredicate(
        [&Settings](const TSharedPtr<FString>& Item) { return *Item == Settings.Type; });
    TypeCombo->SetSelectedItem(Type ? *Type : nullptr);
    TypeTextBox->SetText(FText::FromString(Settings.Type));
    PublishIconCheckBox->SetIsChecked(Settings.bIcon ? ECheckBoxState::Checked : ECheckBoxState::Unchecked);
    PublishFbxCheckBox->SetIsChecked(Settings.bFbx ? ECheckBoxState::Checked : ECheckBoxState::Unchecked);
    PublishTextureCheckBox->SetIsChecked(Settings.bTextures ? ECheckBoxState::Checked : ECheckBoxState::Unchecked);
    RefreshTargetPath();
}

bool SCGToolsPublisherWindow::ValidateBatch(FString& OutDestination, FString& OutError)
{
    OutDestination.Reset();
    OutError.Reset();
    if (!PublishAsset.IsValid()) { OutError = TEXT("所选网格体已失效，请重新选择。"); return false; }
    if (!Config.IsValid()) { OutError = Config.Error; return false; }
    if (GetSelectedProject().IsEmpty() || GetSelectedType().IsEmpty())
    { OutError = TEXT("请选择项目和资产类型。"); return false; }
    if (!IsSafePathComponent(GetAssetName(), OutError) || !IsSafePathComponent(GetSelectedType(), OutError)) { return false; }
    FString FolderType, FolderName;
    if (!ResolveMeshAssetFolder(FolderType, FolderName, OutError)) { return false; }
    if (bSkeletalMeshPublish && !FolderType.Equals(GetSelectedType(), ESearchCase::IgnoreCase))
    {
        OutError = FString::Printf(TEXT("所选类型与资产文件夹不一致。\n资产目录：%s\n请选择类型：%s"), *MeshAssetFolder, *FolderType);
        return false;
    }
    OutDestination = GetAssetRoot();
    return true;
}

bool SCGToolsPublisherWindow::ExportFbx(
    UObject* Asset,
    const FString& DestinationFile,
    FString& OutError
) const
{
    return CGToolsPublisher::ExportMeshFbx(Asset, DestinationFile, OutError);
}

bool SCGToolsPublisherWindow::ExportMeshOutputs(const FString& StagingRoot,
    bool bPublishFbx, bool bPublishIcon, FString& Error) const
{
    const FString AssetName = GetAssetName();
    bool bSucceeded = true;
    if (bPublishFbx) { bSucceeded = ExportFbx(PublishAsset.Get(), StagingRoot / TEXT("FBX") / (AssetName + TEXT(".fbx")), Error); }
    if (bSucceeded && bPublishIcon) { bSucceeded = ExportIcon(PublishAsset.Get(), StagingRoot / TEXT("Icon") / (AssetName + TEXT(".png")), Error); }
    for (const TWeakPtr<SCGToolsPublisherWindow>& WeakPanel : BatchMeshPanels)
    {
        const TSharedPtr<SCGToolsPublisherWindow> Panel = WeakPanel.Pin();
        if (!bSucceeded) { break; }
        if (!Panel.IsValid() || !Panel->PublishAsset.IsValid())
        { bSucceeded = false; Error = TEXT("批量发布中的模型已失效。"); break; }
        const FString ModelName = Panel->AssetData.AssetName.ToString();
        if (ModelName.Equals(AssetName, ESearchCase::IgnoreCase)) { continue; }
        if (Panel.Get() == this)
        {
            IPlatformFile& Files = FPlatformFileManager::Get().GetPlatformFile();
            if (bPublishFbx) { bSucceeded = CopyFileChecked(Files, StagingRoot / TEXT("FBX") / (ModelName + TEXT(".fbx")), StagingRoot / TEXT("FBX") / (AssetName + TEXT(".fbx"))); }
            if (bSucceeded && bPublishIcon) { bSucceeded = CopyFileChecked(Files, StagingRoot / TEXT("Icon") / (ModelName + TEXT(".png")), StagingRoot / TEXT("Icon") / (AssetName + TEXT(".png"))); }
            if (!bSucceeded) { Error = TEXT("无法生成首个模型的 FBX/Icon 副本：") + ModelName; }
            continue;
        }
        if (bPublishFbx) { bSucceeded = ExportFbx(Panel->PublishAsset.Get(), StagingRoot / TEXT("FBX") / (ModelName + TEXT(".fbx")), Error); }
        if (bSucceeded && bPublishIcon) { bSucceeded = Panel->ExportIcon(Panel->PublishAsset.Get(), StagingRoot / TEXT("Icon") / (ModelName + TEXT(".png")), Error); }
    }

    return bSucceeded;
}

bool SCGToolsPublisherWindow::ExportReferencedTextures(
    const TArray<FName>& RootPackageNames,
    const FString& DestinationDirectory,
    int32& OutTextureCount,
    FString& OutError
) const
{
    OutTextureCount = 0;
    IPlatformFile& PlatformFile = FPlatformFileManager::Get().GetPlatformFile();
    PlatformFile.CreateDirectoryTree(*DestinationDirectory);
    if (!PlatformFile.DirectoryExists(*DestinationDirectory))
    {
        OutError = FString::Printf(
            TEXT("无法建立 Texture 发布目录：%s"),
            *DestinationDirectory
        );
        return false;
    }

    FAssetRegistryModule& AssetRegistryModule =
        FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry"));
    IAssetRegistry& Registry = AssetRegistryModule.Get();
    Registry.WaitForCompletion();

    TSet<FName> VisitedPackages;
    TArray<FName> PendingPackages;
    PendingPackages.Append(RootPackageNames);
    while (PendingPackages.Num() > 0)
    {
        const FName PackageName = PendingPackages.Pop(EAllowShrinking::No);
        if (VisitedPackages.Contains(PackageName))
        {
            continue;
        }
        VisitedPackages.Add(PackageName);

        TArray<FName> Dependencies;
        Registry.GetDependencies(PackageName, Dependencies);
        for (const FName Dependency : Dependencies)
        {
            if (Dependency.ToString().StartsWith(TEXT("/Game/"))
                && !VisitedPackages.Contains(Dependency))
            {
                PendingPackages.Add(Dependency);
            }
        }
    }

    TArray<UTexture2D*> Textures;
    for (const FName PackageName : VisitedPackages)
    {
        TArray<FAssetData> Assets;
        Registry.GetAssetsByPackageName(PackageName, Assets);
        for (const FAssetData& DependencyAssetData : Assets)
        {
            if (UTexture2D* Texture = Cast<UTexture2D>(DependencyAssetData.GetAsset()))
            {
                Textures.AddUnique(Texture);
            }
        }
    }
    Textures.Sort([](const UTexture2D& A, const UTexture2D& B)
    {
        return A.GetPathName().Compare(B.GetPathName(), ESearchCase::IgnoreCase) < 0;
    });

    FScopedSlowTask TextureExportProgress(
        FMath::Max(1, Textures.Num()),
        LOCTEXT("ExportingTextureFiles", "正在导出依赖贴图…")
    );
    TSet<FString> UsedBaseNames;
    for (UTexture2D* Texture : Textures)
    {
        TextureExportProgress.EnterProgressFrame(
            1.0f,
            Texture
                ? FText::Format(
                    LOCTEXT("ExportingTextureNamed", "正在导出贴图：{0}"),
                    FText::FromString(Texture->GetName())
                )
                : LOCTEXT("ExportingInvalidTexture", "正在检查贴图…")
        );
        TextureExportProgress.TickProgress();
        if (!Texture || !Texture->Source.IsValid())
        {
            OutError = FString::Printf(
                TEXT("贴图没有可导出的源数据：%s"),
                Texture ? *Texture->GetPathName() : TEXT("<invalid>")
            );
            return false;
        }

        FString BaseName = Texture->GetName();
        FString BaseKey = BaseName.ToLower();
        if (UsedBaseNames.Contains(BaseKey))
        {
            BaseName = Texture->GetOutermost()->GetName();
            BaseName.RemoveFromStart(TEXT("/Game/"));
            BaseName.ReplaceInline(TEXT("/"), TEXT("_"));
            BaseKey = BaseName.ToLower();
        }
        int32 DuplicateIndex = 2;
        const FString UniqueStem = BaseName;
        while (UsedBaseNames.Contains(BaseKey))
        {
            BaseName = FString::Printf(TEXT("%s_%d"), *UniqueStem, DuplicateIndex++);
            BaseKey = BaseName.ToLower();
        }
        UsedBaseNames.Add(BaseKey);

        UAssetExportTask* Task = NewObject<UAssetExportTask>();
        Task->Object = Texture;
        FString Extension;
        UTextureExporterPNG* PngExporter = NewObject<UTextureExporterPNG>(Task);
        if (PngExporter->SupportsObject(Texture))
        {
            Task->Exporter = PngExporter;
            Extension = TEXT("png");
        }
        else
        {
            UTextureExporterEXR* ExrExporter = NewObject<UTextureExporterEXR>(Task);
            if (!ExrExporter->SupportsObject(Texture))
            {
                OutError = FString::Printf(
                    TEXT("贴图格式无法导出为 PNG 或 EXR：%s"),
                    *Texture->GetPathName()
                );
                return false;
            }
            Task->Exporter = ExrExporter;
            Extension = TEXT("exr");
        }

        TArray<FString> FilesBefore;
        IFileManager::Get().FindFiles(
            FilesBefore,
            *(DestinationDirectory / TEXT("*")),
            true,
            false
        );
        Task->Filename = DestinationDirectory / (BaseName + TEXT(".") + Extension);
        Task->bSelected = false;
        Task->bReplaceIdentical = true;
        Task->bPrompt = false;
        Task->bAutomated = true;
        Task->bUseFileArchive = false;
        Task->bWriteEmptyFiles = false;

        const bool bExported = UExporter::RunAssetExportTask(Task);
        TArray<FString> FilesAfter;
        IFileManager::Get().FindFiles(
            FilesAfter,
            *(DestinationDirectory / TEXT("*")),
            true,
            false
        );
        if (!bExported || FilesAfter.Num() <= FilesBefore.Num())
        {
            OutError = FString::Printf(
                TEXT("Texture 导出失败：%s"),
                *Texture->GetPathName()
            );
            if (Task->Errors.Num() > 0)
            {
                OutError += TEXT("\n") + FString::Join(Task->Errors, TEXT("\n"));
            }
            return false;
        }
        ++OutTextureCount;
    }

    return true;
}

bool SCGToolsPublisherWindow::ExportIcon(
    UObject* Asset,
    const FString& DestinationFile,
    FString& OutError
) const
{
    TArray64<uint8> CompressedPng;
    if (CustomIconSize.X > 0
        && CustomIconSize.Y > 0
        && CustomIconPixels.Num() == CustomIconSize.X * CustomIconSize.Y)
    {
        const TArrayView64<const FColor> Colors(
            CustomIconPixels.GetData(),
            static_cast<int64>(CustomIconPixels.Num())
        );
        FImageUtils::PNGCompressImageArray(
            CustomIconSize.X,
            CustomIconSize.Y,
            Colors,
            CompressedPng
        );
    }
    else if (AutomaticIconSize.X > 0
        && AutomaticIconSize.Y > 0
        && AutomaticIconPixels.Num() == AutomaticIconSize.X * AutomaticIconSize.Y)
    {
        const TArrayView64<const FColor> Colors(
            AutomaticIconPixels.GetData(),
            static_cast<int64>(AutomaticIconPixels.Num())
        );
        FImageUtils::PNGCompressImageArray(
            AutomaticIconSize.X,
            AutomaticIconSize.Y,
            Colors,
            CompressedPng
        );
    }
    else
    {
        constexpr int32 IconSize = 512;
        FObjectThumbnail Thumbnail;
        ThumbnailTools::RenderThumbnail(
            Asset,
            IconSize,
            IconSize,
            ThumbnailTools::EThumbnailTextureFlushMode::AlwaysFlush,
            nullptr,
            &Thumbnail
        );

        const int32 Width = Thumbnail.GetImageWidth();
        const int32 Height = Thumbnail.GetImageHeight();
        const TArray<uint8>& ImageData = Thumbnail.GetUncompressedImageData();
        if (Width <= 0 || Height <= 0 || ImageData.Num() != Width * Height * 4)
        {
            OutError = FString::Printf(
                TEXT("UE 未能生成有效的%s缩略图。"),
                *GetAssetKindLabel()
            );
            return false;
        }

        const TArrayView64<const FColor> Colors(
            reinterpret_cast<const FColor*>(ImageData.GetData()),
            static_cast<int64>(Width) * Height
        );
        FImageUtils::PNGCompressImageArray(Width, Height, Colors, CompressedPng);
    }

    IPlatformFile& PlatformFile = FPlatformFileManager::Get().GetPlatformFile();
    PlatformFile.CreateDirectoryTree(*FPaths::GetPath(DestinationFile));
    if (CompressedPng.Num() == 0
        || !FFileHelper::SaveArrayToFile(CompressedPng, *DestinationFile))
    {
        OutError = FString::Printf(TEXT("Icon 写入失败：%s"), *DestinationFile);
        return false;
    }
    return true;
}

bool SCGToolsPublisherWindow::WriteProjectFile(
    const FString& DestinationFile,
    FString& OutError
) const
{
    const TSharedRef<FJsonObject> ProjectObject = MakeShared<FJsonObject>();
    ProjectObject->SetNumberField(TEXT("FileVersion"), 3);
    ProjectObject->SetStringField(
        TEXT("EngineAssociation"),
        FString::Printf(
            TEXT("%d.%d"),
            FEngineVersion::Current().GetMajor(),
            FEngineVersion::Current().GetMinor()
        )
    );
    ProjectObject->SetStringField(TEXT("Category"), TEXT(""));
    ProjectObject->SetStringField(TEXT("Description"), TEXT("Published by CGToolsPublisher"));
    return SaveJsonFile(DestinationFile, ProjectObject, OutError);
}

bool SCGToolsPublisherWindow::PromoteStagedPublish(
    const FString& AssetName,
    const FString& AssetRoot,
    const FString& StagingRoot,
    const FString& ExpectedRelativeAssetFile,
    bool bPublishFbx,
    bool bPublishIcon,
    bool bPublishTextures,
    FString& OutHistoryPath,
    FString& OutError
)
{
    IPlatformFile& PlatformFile = FPlatformFileManager::Get().GetPlatformFile();
    const FString StagedContent = StagingRoot / TEXT("UE/Content");
    const FString StagedProject = StagingRoot / TEXT("UE") / (AssetName + TEXT(".uproject"));
    const FString StagedFbx = StagingRoot / TEXT("FBX");
    const FString StagedIcon = StagingRoot / TEXT("Icon");
    const FString StagedTextures = StagingRoot / TEXT("Texture");
    const FString FinalContent = AssetRoot / TEXT("UE/Content");
    const FString FinalProject = AssetRoot / TEXT("UE") / (AssetName + TEXT(".uproject"));
    const FString FinalFbx = AssetRoot / TEXT("FBX");
    const FString FinalIcon = AssetRoot / TEXT("Icon");
    const FString FinalTextures = AssetRoot / TEXT("Texture");

    // Verify all required staging outputs before backing up or replacing anything.
    if (!PlatformFile.FileExists(*(StagedContent / ExpectedRelativeAssetFile))
        || !PlatformFile.FileExists(*StagedProject)
        || (bPublishFbx && !PlatformFile.FileExists(*(StagedFbx / (AssetName + TEXT(".fbx")))))
        || (bPublishIcon && !PlatformFile.FileExists(*(StagedIcon / (AssetName + TEXT(".png"))))))
    {
        OutError = TEXT("发布暂存目录缺少 UE、FBX 或 Icon 文件，尚未修改服务器内容。");
        return false;
    }

    const bool bHadContent = PlatformFile.DirectoryExists(*FinalContent);
    const bool bHadProject = PlatformFile.FileExists(*FinalProject);
    const bool bHadFbx = bPublishFbx && PlatformFile.DirectoryExists(*FinalFbx);
    const bool bHadIcon = bPublishIcon && PlatformFile.DirectoryExists(*FinalIcon);
    const bool bHadTextures =
        bPublishTextures && PlatformFile.DirectoryExists(*FinalTextures);
    const bool bNeedsBackup =
        bHadContent || bHadProject || bHadFbx || bHadIcon || bHadTextures;

    FString HistoryRoot;
    if (bNeedsBackup)
    {
        HistoryRoot = AssetRoot / TEXT("history") / FString::Printf(
            TEXT("%s_%s"),
            *FDateTime::Now().ToString(TEXT("%Y%m%d_%H%M%S")),
            *FGuid::NewGuid().ToString(EGuidFormats::Digits).Left(8)
        );
        PlatformFile.CreateDirectoryTree(*HistoryRoot);

        if (bHadContent
            && !PlatformFile.CopyDirectoryTree(
                *(HistoryRoot / TEXT("UE/Content")),
                *FinalContent,
                true
            ))
        {
            OutError = TEXT("无法备份旧 UE/Content；当前发布内容未被修改。");
            return false;
        }
        if (bHadProject
            && !CopyFileChecked(
                PlatformFile,
                HistoryRoot / TEXT("UE") / (AssetName + TEXT(".uproject")),
                FinalProject
            ))
        {
            OutError = TEXT("无法备份旧 .uproject；当前发布内容未被修改。");
            return false;
        }
        if (bHadFbx
            && !PlatformFile.CopyDirectoryTree(
                *(HistoryRoot / TEXT("FBX")), *FinalFbx, true))
        {
            OutError = TEXT("无法备份旧 FBX；当前发布内容未被修改。");
            return false;
        }
        if (bHadIcon
            && !PlatformFile.CopyDirectoryTree(
                *(HistoryRoot / TEXT("Icon")), *FinalIcon, true))
        {
            OutError = TEXT("无法备份旧 Icon；当前发布内容未被修改。");
            return false;
        }
        if (bHadTextures
            && !PlatformFile.CopyDirectoryTree(
                *(HistoryRoot / TEXT("Texture")),
                *FinalTextures,
                true
            ))
        {
            OutError = TEXT("无法备份旧 Texture；当前发布内容未被修改。");
            return false;
        }
    }

    auto RestoreOldPublish = [&]()
    {
        PlatformFile.DeleteDirectoryRecursively(*FinalContent);
        if (bHadContent)
        {
            PlatformFile.CopyDirectoryTree(
                *FinalContent,
                *(HistoryRoot / TEXT("UE/Content")),
                true
            );
        }

        PlatformFile.DeleteFile(*FinalProject);
        if (bHadProject)
        {
            CopyFileChecked(
                PlatformFile,
                FinalProject,
                HistoryRoot / TEXT("UE") / (AssetName + TEXT(".uproject"))
            );
        }
        if (bPublishFbx)
        {
            PlatformFile.DeleteDirectoryRecursively(*FinalFbx);
            if (bHadFbx)
            {
                PlatformFile.CopyDirectoryTree(
                    *FinalFbx, *(HistoryRoot / TEXT("FBX")), true);
            }
        }
        if (bPublishIcon)
        {
            PlatformFile.DeleteDirectoryRecursively(*FinalIcon);
            if (bHadIcon)
            {
                PlatformFile.CopyDirectoryTree(
                    *FinalIcon, *(HistoryRoot / TEXT("Icon")), true);
            }
        }
        if (bPublishTextures)
        {
            PlatformFile.DeleteDirectoryRecursively(*FinalTextures);
            if (bHadTextures)
            {
                PlatformFile.CopyDirectoryTree(
                    *FinalTextures,
                    *(HistoryRoot / TEXT("Texture")),
                    true
                );
            }
        }
    };

    PlatformFile.DeleteDirectoryRecursively(*FinalContent);
    PlatformFile.CreateDirectoryTree(*FPaths::GetPath(FinalContent));
    bool bPromotionSucceeded = PlatformFile.CopyDirectoryTree(*FinalContent, *StagedContent, true);
    bPromotionSucceeded = bPromotionSucceeded
        && PlatformFile.FileExists(*(FinalContent / ExpectedRelativeAssetFile));
    bPromotionSucceeded = bPromotionSucceeded
        && CopyFileChecked(PlatformFile, FinalProject, StagedProject);
    if (bPublishFbx)
    {
        bPromotionSucceeded = bPromotionSucceeded
            && PlatformFile.CopyDirectoryTree(*FinalFbx, *StagedFbx, true);
    }
    if (bPublishIcon)
    {
        bPromotionSucceeded = bPromotionSucceeded
            && PlatformFile.CopyDirectoryTree(*FinalIcon, *StagedIcon, true);
    }
    if (bPublishTextures)
    {
        PlatformFile.DeleteDirectoryRecursively(*FinalTextures);
        bPromotionSucceeded = bPromotionSucceeded
            && PlatformFile.DirectoryExists(*StagedTextures)
            && PlatformFile.CopyDirectoryTree(
                *FinalTextures,
                *StagedTextures,
                true
            );
    }

    if (!bPromotionSucceeded)
    {
        RestoreOldPublish();
        OutError = FString::Printf(
            TEXT("提交服务器文件失败，已尝试恢复旧版本。\n备份目录：%s"),
            HistoryRoot.IsEmpty() ? TEXT("（原先没有发布文件）") : *HistoryRoot
        );
        return false;
    }

    OutHistoryPath = bNeedsBackup ? HistoryRoot : FString();
    return true;
}

#undef LOCTEXT_NAMESPACE
