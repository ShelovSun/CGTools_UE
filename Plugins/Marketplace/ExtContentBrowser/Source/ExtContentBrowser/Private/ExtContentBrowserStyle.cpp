// Copyright 2017-2021 marynate. All Rights Reserved.

#include "ExtContentBrowserStyle.h"
#include "Styling/SlateStyleRegistry.h"
#include "Framework/Application/SlateApplication.h"
#include "Slate/SlateGameResources.h"
#include "Interfaces/IPluginManager.h"

#include "DocumentationStyle.h"

TSharedPtr< FSlateStyleSet > FExtContentBrowserStyle::StyleInstance = NULL;

FLinearColor FExtContentBrowserStyle::CustomContentBrowserBorderBackgroundColor(.05f, 0.05f, 0.05f, 1.0f);
FLinearColor FExtContentBrowserStyle::CustomToolbarBackgroundColor(0.0f, 0.0f, 0.0f, .2f);
FLinearColor FExtContentBrowserStyle::CustomSourceViewBackgroundColor(0.0f, 0.0f, 0.0f, .1f);
FLinearColor FExtContentBrowserStyle::CustomAssetViewBackgroundColor(0.0f, 0.0f, 0.0f, .1f);

void FExtContentBrowserStyle::Initialize()
{
	if (!StyleInstance.IsValid())
	{
		StyleInstance = Create();
		FSlateStyleRegistry::RegisterSlateStyle(*StyleInstance);
	}
}

void FExtContentBrowserStyle::Shutdown()
{
	FSlateStyleRegistry::UnRegisterSlateStyle(*StyleInstance);
	ensure(StyleInstance.IsUnique());
	StyleInstance.Reset();
}

FName FExtContentBrowserStyle::GetStyleSetName()
{
	static FName StyleSetName(TEXT("UAssetBrowserStyle"));
	return StyleSetName;
}

FSlateFontInfo FExtContentBrowserStyle::GetFontStyle(FName PropertyName, const ANSICHAR* Specifier /*= NULL*/)
{
	return Get().GetFontStyle(PropertyName, Specifier);
}

#define IMAGE_BRUSH( RelativePath, ... ) FSlateImageBrush( StyleSet->RootToContentDir( RelativePath, TEXT(".png") ), __VA_ARGS__ )
#define BOX_BRUSH( RelativePath, ... ) FSlateBoxBrush( StyleSet->RootToContentDir( RelativePath, TEXT(".png") ), __VA_ARGS__ )
#define BORDER_BRUSH( RelativePath, ... ) FSlateBorderBrush( StyleSet->RootToContentDir( RelativePath, TEXT(".png") ), __VA_ARGS__ )
#define TTF_FONT( RelativePath, ... ) FSlateFontInfo( StyleSet->RootToContentDir( RelativePath, TEXT(".ttf") ), __VA_ARGS__ )
#define OTF_FONT( RelativePath, ... ) FSlateFontInfo( StyleSet->RootToContentDir( RelativePath, TEXT(".otf") ), __VA_ARGS__ )

#define DEFAULT_FONT(...) FCoreStyle::GetDefaultFontStyle(__VA_ARGS__)

const FVector2D Icon12x12(12.0f, 12.0f);
const FVector2D Icon16x16(16.0f, 16.0f);
const FVector2D Icon20x20(20.0f, 20.0f);
const FVector2D Icon24x24(24.0f, 24.0f);
const FVector2D Icon40x40(40.0f, 40.0f);

TSharedRef< FSlateStyleSet > FExtContentBrowserStyle::Create()
{
	TSharedRef< FSlateStyleSet > StyleSet = MakeShareable(new FSlateStyleSet("UAssetBrowserStyle"));
	StyleSet->SetContentRoot(IPluginManager::Get().FindPlugin("ExtContentBrowser")->GetBaseDir() / TEXT("Resources"));

	// Icons
	{
		StyleSet->Set("UAssetBrowser.Icon16x", new IMAGE_BRUSH(TEXT("Icons/UAssetBrowserIcon24"), Icon16x16));
		StyleSet->Set("UAssetBrowser.Icon24x", new IMAGE_BRUSH(TEXT("Icons/UAssetBrowserIcon24"), Icon24x24));
		StyleSet->Set("UAssetBrowser.OpenUAssetBrowser", new IMAGE_BRUSH(TEXT("Icons/UAssetBrowserIcon64"), Icon40x40));
		StyleSet->Set("UAssetBrowser.OpenUAssetBrowser.Small", new IMAGE_BRUSH(TEXT("Icons/UAssetBrowserIcon24"), Icon16x16));
	}

	// Images
	{
		StyleSet->Set("UAssetBrowser.Help", new IMAGE_BRUSH(TEXT("Images/Documentation16"), Icon16x16));

		StyleSet->Set("UAssetBrowser.Rotation16px", new IMAGE_BRUSH(TEXT("Images/Loading"), Icon16x16));
		
		StyleSet->Set("UAssetBrowser.ShowSourcesView", new IMAGE_BRUSH(TEXT("Images/AssetTreeToggleExpanded16"), Icon16x16));
		StyleSet->Set("UAssetBrowser.HideSourcesView", new IMAGE_BRUSH(TEXT("Images/AssetTreeToggleCollapsed16"), Icon16x16));

		StyleSet->Set("UAssetBrowser.ShowDependencyViewer", new IMAGE_BRUSH(TEXT("Images/DependencyViewerExpanded16"), Icon16x16));
		StyleSet->Set("UAssetBrowser.HideDependencyViewer", new IMAGE_BRUSH(TEXT("Images/DependencyViewer16"), Icon16x16));

		StyleSet->Set("UAssetBrowser.ValidationUknown", new IMAGE_BRUSH(TEXT("Images/ValidationUknown"), Icon16x16));
		StyleSet->Set("UAssetBrowser.ValidationValid", new IMAGE_BRUSH(TEXT("Images/ValidationValid"), Icon16x16));
		StyleSet->Set("UAssetBrowser.ValidationInValid", new IMAGE_BRUSH(TEXT("Images/ValidationInValid"), Icon16x16));
		StyleSet->Set("UAssetBrowser.ValidationIssue", new IMAGE_BRUSH(TEXT("Images/ValidationIssue"), Icon16x16));

		// Folder Icons
		StyleSet->Set("UAssetBrowser.AssetTreeFolderDeveloper", new IMAGE_BRUSH("Images/FolderClosed", FVector2D(18, 16))); 
		StyleSet->Set("UAssetBrowser.AssetTreeFolderOpenCode", new IMAGE_BRUSH("Images/FolderOpen_Code", FVector2D(18, 16)));
		StyleSet->Set("UAssetBrowser.AssetTreeFolderClosedCode", new IMAGE_BRUSH("Images/FolderClosed_Code", FVector2D(18, 16)));

		StyleSet->Set("UAssetBrowser.AssetTreeFolderClosed", new IMAGE_BRUSH("Images/FolderClosed", FVector2D(18, 16)));
		StyleSet->Set("UAssetBrowser.AssetTreeFolderOpen", new IMAGE_BRUSH("Images/FolderOpen", FVector2D(18, 16)));
		
		StyleSet->Set("UAssetBrowser.AssetTreeFolderClosedPlugin", new IMAGE_BRUSH("Images/FolderClosed_Plugin", FVector2D(18, 16)));
		StyleSet->Set("UAssetBrowser.AssetTreeFolderOpenPlugin", new IMAGE_BRUSH("Images/FolderOpen_Plugin", FVector2D(18, 16)));

		StyleSet->Set("UAssetBrowser.AssetTreeFolderClosedProject", new IMAGE_BRUSH("Images/FolderClosed_Project", FVector2D(18, 16)));
		StyleSet->Set("UAssetBrowser.AssetTreeFolderOpenProject", new IMAGE_BRUSH("Images/FolderOpen_Project", FVector2D(18, 16)));
		
		StyleSet->Set("UAssetBrowser.AssetTreeFolderClosedVaultCache", new IMAGE_BRUSH("Images/FolderClosed_VaultCache", FVector2D(18, 16)));
		StyleSet->Set("UAssetBrowser.AssetTreeFolderOpenVaultCache", new IMAGE_BRUSH("Images/FolderOpen_VaultCache", FVector2D(18, 16)));
	}

	// Font
	{
		StyleSet->Set("UAssetBrowser.SourceTreeRootItemFont", DEFAULT_FONT("Regular", 12));
		StyleSet->Set("UAssetBrowser.SourceTreeRootItemFont.LoadingFont", DEFAULT_FONT("Regular", 9));

		StyleSet->Set("UAssetBrowser.SourceTreeItemFont", DEFAULT_FONT("Regular", 10));
	}

	// TextStyle
	{
		FTextBlockStyle NormalText = FTextBlockStyle()
			.SetFont(DEFAULT_FONT("Regular", FCoreStyle::RegularTextSize))
			.SetColorAndOpacity(FSlateColor::UseForeground())
			.SetShadowOffset(FVector2D::ZeroVector)
			.SetShadowColorAndOpacity(FLinearColor::Black);

		StyleSet->Set("UAssetBrowser.TopBar.Font", FTextBlockStyle(NormalText)
			.SetFont(DEFAULT_FONT("Bold", 11))
			.SetColorAndOpacity(FLinearColor(1.0f, 1.0f, 1.0f))
			.SetHighlightColor(FLinearColor(1.0f, 1.0f, 1.0f))
			.SetShadowOffset(FVector2D(1, 1))
			.SetShadowColorAndOpacity(FLinearColor(0, 0, 0, 0.9f)));

		StyleSet->Set("UAssetBrowser.TopBar.DebugFont", FTextBlockStyle(NormalText)
			.SetFont(DEFAULT_FONT("Regular", 10))
			.SetColorAndOpacity(FLinearColor(.7f, .7f, .7f))
			.SetHighlightColor(FLinearColor(1.0f, 1.0f, 1.0f))
			.SetShadowOffset(FVector2D(1, 1))
			.SetShadowColorAndOpacity(FLinearColor(0, 0, 0, 0.9f)));

		StyleSet->Set("UAssetBrowser.ChangeLogHeaderText", FTextBlockStyle(NormalText)
			.SetFont(DEFAULT_FONT("Regular", 10))
			.SetColorAndOpacity(FLinearColor(1.0f, 1.0f, 1.0f))
			.SetHighlightColor(FLinearColor(1.0f, 1.0f, 1.0f))
			.SetShadowOffset(FVector2D(1, 1))
			.SetShadowColorAndOpacity(FLinearColor(0, 0, 0, 0.9f)));

		StyleSet->Set("UAssetBrowser.SourceTreeRootItem.Loading", FTextBlockStyle(NormalText)
			.SetFont(DEFAULT_FONT("Regular", 8))
			.SetColorAndOpacity(FLinearColor(0.6f, 0.6f, 0.6f)));

		StyleSet->Set("UAssetBrowser.AssetThumbnail.EngineOverlay", FTextBlockStyle(NormalText)
			.SetFont(DEFAULT_FONT("Regular", 9))
			.SetColorAndOpacity(FLinearColor(1.0, 1.0, 1.0, 0.9))
			.SetShadowColorAndOpacity(FLinearColor(0, 0, 0, 0.8))
			.SetShadowOffset(FVector2D(1.0f, 1.0f)));
	}

	// Colors
	{
		StyleSet->Set("ErrorReporting.HardReferenceColor", FLinearColor(0.35f, 0, 0));
		StyleSet->Set("ErrorReporting.HardReferenceColor.Darker", FLinearColor(0.35f * 0.6f, 0, 0));
		StyleSet->Set("ErrorReporting.SoftReferenceColor", FLinearColor(0.828f, 0.364f, 0.003f));
		StyleSet->Set("ErrorReporting.SoftReferenceColor.Darker", FLinearColor(0.828f * 0.6f, 0.364f * 0.6f, 0.003f));
	}

	return StyleSet;
}

void FExtContentBrowserStyle::ReloadTextures()
{
	if (FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().GetRenderer()->ReloadTextureResources();
	}
}


FDocumentationStyle FExtContentBrowserStyle::GetChangLogDocumentationStyle()
{
	FDocumentationStyle DocumentationStyle;
	{
		DocumentationStyle
			.ContentStyle(TEXT("ChangeLog.Content.Text"))
			.BoldContentStyle(TEXT("ChangeLog.Content.TextBold"))
			.NumberedContentStyle(TEXT("ChangeLog.Content.Text"))
			.Header1Style(TEXT("ChangeLog.Content.HeaderText1"))
			.Header2Style(TEXT("ChangeLog.Content.HeaderText2"))
			.HyperlinkStyle(TEXT("Tutorials.Content.Hyperlink"))
			.HyperlinkTextStyle(TEXT("Tutorials.Content.HyperlinkText"))
			.SeparatorStyle(TEXT("Tutorials.Separator"));
	}
	return DocumentationStyle;
}


const ISlateStyle& FExtContentBrowserStyle::Get()
{
	return *StyleInstance;
}


#undef IMAGE_BRUSH
#undef BOX_BRUSH
#undef BORDER_BRUSH
#undef TTF_FONT
#undef OTF_FONT
#undef DEFAULT_FONT