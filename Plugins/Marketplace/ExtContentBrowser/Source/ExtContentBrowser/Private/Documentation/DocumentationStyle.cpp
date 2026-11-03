// Copyright 2017-2021 marynate. All Rights Reserved.

#include "DocumentationStyle.h"

#include "Slate/SlateGameResources.h"
#include "Interfaces/IPluginManager.h"
#include "Styling/SlateStyle.h"
#include "Styling/SlateStyleRegistry.h"
#include "Styling/CoreStyle.h"
#include "Framework/Application/SlateApplication.h"
#include "EditorStyleSet.h"

#include "DocumentationDefines.h"

#define IMAGE_BRUSH( RelativePath, ... ) FSlateImageBrush( StyleSet->RootToContentDir( RelativePath, TEXT(".png") ), __VA_ARGS__ )
#define BORDER_BRUSH( RelativePath, ... ) FSlateBorderBrush( StyleSet->RootToContentDir( RelativePath, TEXT(".png") ), __VA_ARGS__ )
#define BOX_BRUSH( RelativePath, ... ) FSlateBoxBrush( StyleSet->RootToContentDir( RelativePath, TEXT(".png") ), __VA_ARGS__ )
#define DEFAULT_FONT(...) FCoreStyle::GetDefaultFontStyle(__VA_ARGS__)

const ISlateStyle& UAssetBrowserDOC::FExtDocumentationStyle::Get()
{
	if (const ISlateStyle* AppStyle = FSlateStyleRegistry::FindSlateStyle(DocumentationStyleSetName))
	{
		return *AppStyle;
	}

	return FAppStyle::Get();
}

FDocumentationStyle UAssetBrowserDOC::FExtDocumentationStyle::GetDefaultDocumentationStyle()
{
	FDocumentationStyle DocumentationStyle;
	{
		DocumentationStyle
			.ContentStyle(TEXT("Tutorials.Content.Text"))
			.BoldContentStyle(TEXT("Tutorials.Content.TextBold"))
			.NumberedContentStyle(TEXT("Tutorials.Content.Text"))
			.Header1Style(TEXT("Tutorials.Content.HeaderText1"))
			.Header2Style(TEXT("Tutorials.Content.HeaderText2"))
			.HyperlinkStyle(TEXT("Tutorials.Content.Hyperlink"))
			.HyperlinkTextStyle(TEXT("Tutorials.Content.HyperlinkText"))
			.SeparatorStyle(TEXT("Tutorials.Separator"));
	}
	return DocumentationStyle;
}

TSharedPtr< FSlateStyleSet > UAssetBrowserDOC::FExtDocumentationStyle::StyleSet = nullptr;
void UAssetBrowserDOC::FExtDocumentationStyle::Initialize()
{

	// Only register once
	if (StyleSet.IsValid())
	{
		return;
	}

	StyleSet = MakeShareable(new FSlateStyleSet(DocumentationStyleSetName));
	StyleSet->SetCoreContentRoot(FPaths::EngineContentDir() / TEXT("Slate"));
	StyleSet->SetContentRoot(FPaths::EngineContentDir() / TEXT("Editor/Slate"));

	const FTextBlockStyle& NormalText = FAppStyle::Get().GetWidgetStyle<FTextBlockStyle>("NormalText");

	// Documentation
	{
		// Documentation tooltip defaults
		const FSlateColor HyperlinkColor(FLinearColor(0.1f, 0.1f, 0.5f));
		{
			const FTextBlockStyle DocumentationTooltipText = FTextBlockStyle(NormalText)
				.SetFont(DEFAULT_FONT("Regular", 9))
				.SetColorAndOpacity(FLinearColor::Black);
			StyleSet->Set("Documentation.SDocumentationTooltip", FTextBlockStyle(DocumentationTooltipText));

			const FTextBlockStyle DocumentationTooltipTextSubdued = FTextBlockStyle(NormalText)
				.SetFont(DEFAULT_FONT("Regular", 8))
				.SetColorAndOpacity(FLinearColor(0.1f, 0.1f, 0.1f));
			StyleSet->Set("Documentation.SDocumentationTooltipSubdued", FTextBlockStyle(DocumentationTooltipTextSubdued));

			const FTextBlockStyle DocumentationTooltipHyperlinkText = FTextBlockStyle(NormalText)
				.SetFont(DEFAULT_FONT("Regular", 8))
				.SetColorAndOpacity(HyperlinkColor);
			StyleSet->Set("Documentation.SDocumentationTooltipHyperlinkText", FTextBlockStyle(DocumentationTooltipHyperlinkText));

			const FButtonStyle DocumentationTooltipHyperlinkButton = FButtonStyle()
				.SetNormal(BORDER_BRUSH("Old/HyperlinkDotted", FMargin(0, 0, 0, 3 / 16.0f), HyperlinkColor))
				.SetPressed(FSlateNoResource())
				.SetHovered(BORDER_BRUSH("Old/HyperlinkUnderline", FMargin(0, 0, 0, 3 / 16.0f), HyperlinkColor));
			StyleSet->Set("Documentation.SDocumentationTooltipHyperlinkButton", FButtonStyle(DocumentationTooltipHyperlinkButton));
		}

		// Documentation defaults
		const FTextBlockStyle DocumentationText = FTextBlockStyle(NormalText)
			.SetColorAndOpacity(FLinearColor::Black)
			.SetFont(DEFAULT_FONT("Regular", 11));

		const FTextBlockStyle DocumentationHyperlinkText = FTextBlockStyle(DocumentationText)
			.SetColorAndOpacity(HyperlinkColor);

		const FTextBlockStyle DocumentationHeaderText = FTextBlockStyle(NormalText)
			.SetColorAndOpacity(FLinearColor::Black)
			.SetFont(DEFAULT_FONT("Black", 32));

		const FButtonStyle DocumentationHyperlinkButton = FButtonStyle()
			.SetNormal(BORDER_BRUSH("Old/HyperlinkDotted", FMargin(0, 0, 0, 3 / 16.0f), HyperlinkColor))
			.SetPressed(FSlateNoResource())
			.SetHovered(BORDER_BRUSH("Old/HyperlinkUnderline", FMargin(0, 0, 0, 3 / 16.0f), HyperlinkColor));

		StyleSet->Set("Documentation.Content", FTextBlockStyle(DocumentationText));

		const FHyperlinkStyle DocumentationHyperlink = FHyperlinkStyle()
			.SetUnderlineStyle(DocumentationHyperlinkButton)
			.SetTextStyle(DocumentationText)
			.SetPadding(FMargin(0.0f));
		StyleSet->Set("Documentation.Hyperlink", DocumentationHyperlink);

		StyleSet->Set("Documentation.Hyperlink.Button", FButtonStyle(DocumentationHyperlinkButton));
		StyleSet->Set("Documentation.Hyperlink.Text", FTextBlockStyle(DocumentationHyperlinkText));
		StyleSet->Set("Documentation.NumberedContent", FTextBlockStyle(DocumentationText));
		StyleSet->Set("Documentation.BoldContent", FTextBlockStyle(DocumentationText)
			.SetTypefaceFontName(TEXT("Bold")));

		StyleSet->Set("Documentation.Header1", FTextBlockStyle(DocumentationHeaderText)
			.SetFontSize(32));

		StyleSet->Set("Documentation.Header2", FTextBlockStyle(DocumentationHeaderText)
			.SetFontSize(24));

		StyleSet->Set("Documentation.Separator", new BOX_BRUSH("Common/Separator", 1 / 4.0f, FLinearColor(1, 1, 1, 0.5f)));
	}

	{
		//StyleSet->Set("Documentation.ToolTip.Background", new BOX_BRUSH("Tutorials/TutorialContentBackground", FMargin(4 / 16.0f)));
	}

	// Tutorial
	{
		const FTextBlockStyle RichTextNormal = FTextBlockStyle()
			.SetFont(DEFAULT_FONT("Regular", 11))
			.SetColorAndOpacity(FSlateColor::UseForeground())
			.SetShadowOffset(FVector2D::ZeroVector)
			.SetShadowColorAndOpacity(FLinearColor::Black)
			.SetHighlightColor(FLinearColor(0.02f, 0.3f, 0.0f))
			.SetHighlightShape(BOX_BRUSH("Common/TextBlockHighlightShape", FMargin(3.f / 8.f)));

		StyleSet->Set("Tutorials.Content.Text", RichTextNormal);

		StyleSet->Set("Tutorials.Content.TextBold", FTextBlockStyle(RichTextNormal)
			.SetFont(DEFAULT_FONT("Bold", 11)));

		StyleSet->Set("Tutorials.Content.HeaderText1", FTextBlockStyle(RichTextNormal)
			.SetFontSize(20));

		StyleSet->Set("Tutorials.Content.HeaderText2", FTextBlockStyle(RichTextNormal)
			.SetFontSize(16));

		const FButtonStyle RichTextHyperlinkButton = FButtonStyle()
			.SetNormal(BORDER_BRUSH("Old/HyperlinkDotted", FMargin(0, 0, 0, 3 / 16.0f), FLinearColor::Blue))
			.SetPressed(FSlateNoResource())
			.SetHovered(BORDER_BRUSH("Old/HyperlinkUnderline", FMargin(0, 0, 0, 3 / 16.0f), FLinearColor::Blue));

		const FTextBlockStyle RichTextHyperlinkText = FTextBlockStyle(RichTextNormal)
			.SetColorAndOpacity(FLinearColor::Blue);

		StyleSet->Set("Tutorials.Content.HyperlinkText", RichTextHyperlinkText);

		const FHyperlinkStyle RichTextHyperlink = FHyperlinkStyle()
			.SetUnderlineStyle(RichTextHyperlinkButton)
			.SetTextStyle(RichTextHyperlinkText)
			.SetPadding(FMargin(0.0f));
		StyleSet->Set("Tutorials.Content.Hyperlink", RichTextHyperlink);

		StyleSet->Set("Tutorials.Content.ExternalLink", new IMAGE_BRUSH("Tutorials/ExternalLink", FVector2f(16.0f, 16.0f), FLinearColor::Blue));

		StyleSet->Set("Tutorials.Separator", new BOX_BRUSH("Common/Separator", 1 / 4.0f, FLinearColor::Black));
	}

	// ChangLog
	{
		const FTextBlockStyle RichTextNormal = FTextBlockStyle()
			.SetFont(DEFAULT_FONT("Regular", 10))
			.SetColorAndOpacity(FSlateColor::UseForeground())
			.SetShadowOffset(FVector2D::ZeroVector)
			.SetShadowColorAndOpacity(FLinearColor::Black)
			.SetHighlightColor(FLinearColor(0.02f, 0.3f, 0.0f))
			.SetHighlightShape(BOX_BRUSH("Common/TextBlockHighlightShape", FMargin(3.f / 8.f)));

		const FLinearColor ColorChangeLogText(0.8f, 0.8f, 0.8f, 0.7f);
		StyleSet->Set("ChangeLog.Content.Text", FTextBlockStyle(RichTextNormal)
			.SetColorAndOpacity(ColorChangeLogText));

		StyleSet->Set("ChangeLog.Content.TextBold", FTextBlockStyle(RichTextNormal)
			.SetFont(DEFAULT_FONT("Bold", 10)));

		StyleSet->Set("ChangeLog.Content.HeaderText1", FTextBlockStyle(RichTextNormal)
			.SetFont(DEFAULT_FONT("Bold", 10)));

		StyleSet->Set("ChangeLog.Content.HeaderText2", FTextBlockStyle(RichTextNormal)
			.SetFont(DEFAULT_FONT("Bold", 11)));
	}

	FSlateStyleRegistry::RegisterSlateStyle(*StyleSet.Get());
};

void UAssetBrowserDOC::FExtDocumentationStyle::Shutdown()
{
	if (StyleSet.IsValid())
	{
		FSlateStyleRegistry::UnRegisterSlateStyle(*StyleSet.Get());
		ensure(StyleSet.IsUnique());
		StyleSet.Reset();
	}
}

#undef IMAGE_BRUSH
#undef BORDER_BRUSH
#undef BOX_BRUSH
#undef DEFAULT_FONT