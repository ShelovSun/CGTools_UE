// Copyright 1998-2017 Epic Games, Inc. All Rights Reserved.

#include "Documentation.h"
#include "Misc/Paths.h"
#include "Styling/CoreStyle.h"
#include "Widgets/SToolTip.h"
#include "Misc/MessageDialog.h"
#include "HAL/FileManager.h"
#include "Misc/CommandLine.h"
#include "Dialogs/Dialogs.h"
#include "SDocumentationAnchor.h"
#include "UDNParser.h"
#include "DocumentationPage.h"
#include "DocumentationLink.h"
#include "SExtDocumentationToolTip.h"
#include "Interfaces/IAnalyticsProvider.h"
#include "EngineAnalytics.h"


#define LOCTEXT_NAMESPACE "DocumentationActor"

TSharedRef< IDocumentation > UAssetBrowserDOC::FExtDocumentation::Create()
{
	return MakeShareable( new UAssetBrowserDOC::FExtDocumentation() );
}

UAssetBrowserDOC::FExtDocumentation::FExtDocumentation()
{

}

UAssetBrowserDOC::FExtDocumentation::~FExtDocumentation()
{

}

bool UAssetBrowserDOC::FExtDocumentation::OpenHome(FDocumentationSourceInfo Source, const FString& BaseUrlId) const
{
	return Open(TEXT("%ROOT%"), Source, BaseUrlId);
}

bool UAssetBrowserDOC::FExtDocumentation::OpenHome(const FCultureRef& Culture, FDocumentationSourceInfo Source, const FString& BaseUrlId) const
{
	return Open(TEXT("%ROOT%"), Culture, Source, BaseUrlId);
}

bool UAssetBrowserDOC::FExtDocumentation::OpenAPIHome(FDocumentationSourceInfo Source) const
{
	FString Url;
	FUnrealEdMisc::Get().GetURL(TEXT("APIDocsURL"), Url, true);

	if (!Url.IsEmpty())
	{
		FUnrealEdMisc::Get().ReplaceDocumentationURLWildcards(Url, FInternationalization::Get().GetCurrentCulture());
		FPlatformProcess::LaunchURL(*Url, nullptr, nullptr);

		return true;
	}
	return false;
}

bool UAssetBrowserDOC::FExtDocumentation::Open(const FString& Link, FDocumentationSourceInfo Source, const FString& BaseUrlId) const
{
	FString DocumentationUrl;

	// Warn the user if they are opening a URL
	if (Link.StartsWith(TEXT("http")) || Link.StartsWith(TEXT("https")))
	{
		FText Message = LOCTEXT("OpeningURLMessage", "You are about to open an external URL. This will open your web browser. Do you want to proceed?");
		FText URLDialog = LOCTEXT("OpeningURLTitle", "Open external link");

		FSuppressableWarningDialog::FSetupInfo Info(Message, URLDialog, "SuppressOpenURLWarning");
		Info.ConfirmText = LOCTEXT("OpenURL_yes", "Yes");
		Info.CancelText = LOCTEXT("OpenURL_no", "No");
		FSuppressableWarningDialog OpenURLWarning(Info);
		if (OpenURLWarning.ShowModal() == FSuppressableWarningDialog::Cancel)
		{
			return false;
		}
		else
		{
			FPlatformProcess::LaunchURL(*Link, nullptr, nullptr);
			return true;
		}
	}

	if (!FParse::Param(FCommandLine::Get(), TEXT("testdocs")))
	{
		FString OnDiskPath = FExtDocumentationLink::ToFilePath(Link);
		if (IFileManager::Get().FileSize(*OnDiskPath) != INDEX_NONE)
		{
			DocumentationUrl = FExtDocumentationLink::ToFileUrl(Link, Source);
		}
	}


	if (DocumentationUrl.IsEmpty())
	{
		// When opening a doc website we always request the most ideal culture for our documentation.
		// The DNS will redirect us if necessary.
		DocumentationUrl = FExtDocumentationLink::ToUrl(Link, Source, BaseUrlId);
	}

	if (!DocumentationUrl.IsEmpty())
	{
		FPlatformProcess::LaunchURL(*DocumentationUrl, NULL, NULL);
	}

	if (!DocumentationUrl.IsEmpty() && FEngineAnalytics::IsAvailable())
	{
		FEngineAnalytics::GetProvider().RecordEvent(TEXT("Editor.Usage.Documentation"), TEXT("OpenedPage"), Link);
	}

	return !DocumentationUrl.IsEmpty();
}

bool UAssetBrowserDOC::FExtDocumentation::Open(const FString& Link, const FCultureRef& Culture, FDocumentationSourceInfo Source, const FString& BaseUrlId) const
{
	FString DocumentationUrl;

	if (!FParse::Param(FCommandLine::Get(), TEXT("testdocs")))
	{
		FString OnDiskPath = FExtDocumentationLink::ToFilePath(Link, Culture);
		if (IFileManager::Get().FileSize(*OnDiskPath) != INDEX_NONE)
		{
			DocumentationUrl = FExtDocumentationLink::ToFileUrl(Link, Culture, Source);
		}
	}

	if (DocumentationUrl.IsEmpty())
	{
		DocumentationUrl = FExtDocumentationLink::ToUrl(Link, Culture, Source, BaseUrlId);
	}

	if (!DocumentationUrl.IsEmpty())
	{
		FPlatformProcess::LaunchURL(*DocumentationUrl, NULL, NULL);
	}

	if (!DocumentationUrl.IsEmpty() && FEngineAnalytics::IsAvailable())
	{
		FEngineAnalytics::GetProvider().RecordEvent(TEXT("Editor.Usage.Documentation"), TEXT("OpenedPage"), Link);
	}

	return !DocumentationUrl.IsEmpty();
}

TSharedRef< SWidget > UAssetBrowserDOC::FExtDocumentation::CreateAnchor(const TAttribute<FString>& Link, const FString& PreviewLink, const FString& PreviewExcerptName, const TAttribute<FString>& BaseUrlId) const
{
	return SNew( SExtDocumentationAnchor )
		.Link(Link)
		.PreviewLink(PreviewLink)
		.PreviewExcerptName(PreviewExcerptName)
		.BaseUrlId(BaseUrlId);
}

TSharedRef< IDocumentationPage > UAssetBrowserDOC::FExtDocumentation::GetPage( const FString& Link, const TSharedPtr< FParserConfiguration >& Config, const FDocumentationStyle& Style )
{
	TSharedPtr< IDocumentationPage > Page;
	const TWeakPtr< IDocumentationPage >* ExistingPagePtr = LoadedPages.Find( Link );

	if ( ExistingPagePtr != NULL )
	{
		const TSharedPtr< IDocumentationPage > ExistingPage = ExistingPagePtr->Pin();
		if ( ExistingPage.IsValid() )
		{
			Page = ExistingPage;
		}
	}

	if ( !Page.IsValid() )
	{
		Page = FExtDocumentationPage::Create( Link, FExtUDNParser::Create( Config, Style ) );
		LoadedPages.Add( Link, TWeakPtr< IDocumentationPage >( Page ) );
	}

	return Page.ToSharedRef();
}

bool UAssetBrowserDOC::FExtDocumentation::PageExists(const FString& Link) const
{
	const TWeakPtr< IDocumentationPage >* ExistingPagePtr = LoadedPages.Find(Link);
	if (ExistingPagePtr != NULL)
	{
		return true;
	}

	for (const FString& SourcePath : SourcePaths)
	{
		FString LinkPath = FExtDocumentationLink::ToSourcePath(Link, SourcePath);
		if (FPaths::FileExists(LinkPath))
		{
			return true;
		}
	}
	return false;
}

bool UAssetBrowserDOC::FExtDocumentation::PageExists(const FString& Link, const FCultureRef& Culture) const
{
	const TWeakPtr< IDocumentationPage >* ExistingPagePtr = LoadedPages.Find(Link);
	if (ExistingPagePtr != NULL)
	{
		return true;
	}

	for (const FString& SourcePath : SourcePaths)
	{
		FString LinkPath = FExtDocumentationLink::ToSourcePath(Link, Culture, SourcePath);
		if (FPaths::FileExists(LinkPath))
		{
			return true;
		}
	}
	return false;
}

const TArray < FString >& UAssetBrowserDOC::FExtDocumentation::GetSourcePaths() const
{
	return SourcePaths;
}

TSharedRef< class SToolTip > UAssetBrowserDOC::FExtDocumentation::CreateToolTip(const TAttribute<FText>& Text, const TSharedPtr<SWidget>& OverrideContent, const FString& Link, const FString& ExcerptName) const
{
	return CreateToolTip(Text, OverrideContent, Link, ExcerptName, FText());
}

TSharedRef< class SToolTip > UAssetBrowserDOC::FExtDocumentation::CreateToolTip(const TAttribute<FText>& Text, const TSharedPtr<SWidget>& OverrideContent, const FString& Link, const FString& ExcerptName, const TAttribute<FText>& Shortcut) const
{
	TSharedPtr< SExtDocumentationToolTip > DocToolTip;

	if ( !Text.IsBound() && Text.Get().IsEmpty() )
	{
		return SNew( SToolTip );
	}

	// hack: use OverrideContent as flag to always show full tooltip
	if (OverrideContent.IsValid())
	{
		SAssignNew(DocToolTip, SExtDocumentationToolTip)
			.Text(Text)
			.DocumentationLink(Link)
			.ExcerptName(ExcerptName)
			.AlwaysShowFullToolTip(true);
	}
	else
	{
		SAssignNew( DocToolTip, SExtDocumentationToolTip )
		.Text( Text )
		.DocumentationLink( Link )
		.ExcerptName( ExcerptName );
	}

	return SNew( SToolTip )
		.IsInteractive( DocToolTip.ToSharedRef(), &SExtDocumentationToolTip::IsInteractive )

		// Emulate text-only tool-tip styling that SToolTip uses when no custom content is supplied.  We want documentation tool-tips to
		// be styled just like text-only tool-tips
		.BorderImage( FCoreStyle::Get().GetBrush("ToolTip.BrightBackground") )
		.TextMargin(FMargin(11.0f))
		[
			DocToolTip.ToSharedRef()
		];
}

TSharedRef< class SToolTip > UAssetBrowserDOC::FExtDocumentation::CreateToolTip(const TAttribute<FText>& Text, const TSharedRef<SWidget>& OverrideContent, const TSharedPtr<SVerticalBox>& DocVerticalBox, const FString& Link, const FString& ExcerptName) const
{
	TSharedRef<SExtDocumentationToolTip> DocToolTip =
		SNew(SExtDocumentationToolTip)
		.Text(Text)
		.DocumentationLink(Link)
		.ExcerptName(ExcerptName)
		.AddDocumentation(false)
		.DocumentationMargin(7)
		[
			OverrideContent
		];

	if (DocVerticalBox.IsValid())
	{
		DocToolTip->AddDocumentation(DocVerticalBox);
	}

	return SNew(SToolTip)
		.IsInteractive(DocToolTip, &SExtDocumentationToolTip::IsInteractive)

		// Emulate text-only tool-tip styling that SToolTip uses when no custom content is supplied.  We want documentation tool-tips to
		// be styled just like text-only tool-tips
		.BorderImage( FCoreStyle::Get().GetBrush("ToolTip.BrightBackground") )
		.TextMargin(FMargin(11.0f))
		[
			DocToolTip
		];
}

bool UAssetBrowserDOC::FExtDocumentation::RegisterBaseUrl(const FString& Id, const FString& Url)
{
	if (!Id.IsEmpty() && !Url.IsEmpty())
	{
		if (!RegisteredBaseUrls.Contains(Id))
		{
			RegisteredBaseUrls.Add(Id, Url);
			return true;
		}
		//UE_LOG(LogDocumentation, Warning, TEXT("Could not register documentation base URL with ID: %s. This ID is already in use."), *Id);
		return false;
	}
	return false;
}

FString UAssetBrowserDOC::FExtDocumentation::GetBaseUrl(const FString& Id) const
{
	if (!Id.IsEmpty())
	{
		const FString* BaseUrl = RegisteredBaseUrls.Find(Id);
		if (BaseUrl != NULL && !BaseUrl->IsEmpty())
		{
			return *BaseUrl;
		}
		//UE_LOG(LogDocumentation, Warning, TEXT("Could not resolve base URL with ID: %s. It may not have been registered."), *Id);
	}

	FString DefaultUrl;
	FUnrealEdMisc::Get().GetURL(TEXT("DocumentationURL"), DefaultUrl, true);
	return DefaultUrl;
}

bool UAssetBrowserDOC::FExtDocumentation::RegisterRedirect(const FName& Owner, const FDocumentationRedirect& Redirect)
{
	return RedirectRegistry.Register(Owner, Redirect);
}

void UAssetBrowserDOC::FExtDocumentation::UnregisterRedirects(const FName& Owner)
{
	RedirectRegistry.UnregisterAll(Owner);
}


#undef LOCTEXT_NAMESPACE
