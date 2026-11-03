// Copyright 1998-2017 Epic Games, Inc. All Rights Reserved.

#include "DocumentationPage.h"

#include "ExtDocumentation.h"

TSharedRef< IDocumentationPage > UAssetBrowserDOC::FExtDocumentationPage::Create( const FString& Link, const TSharedRef< FExtUDNParser >& Parser )
{
	return MakeShareable( new UAssetBrowserDOC::FExtDocumentationPage( Link, Parser ) );
}

UAssetBrowserDOC::FExtDocumentationPage::~FExtDocumentationPage()
{

}

bool UAssetBrowserDOC::FExtDocumentationPage::GetExcerptContent( FExcerpt& Excerpt )
{
	for (int32 Index = 0; Index < StoredExcerpts.Num(); ++Index)
	{
		if ( Excerpt.Name == StoredExcerpts[ Index ].Name )
		{
			Parser->GetExcerptContent( Link, StoredExcerpts[ Index ] );
			Excerpt.Content = StoredExcerpts[ Index ].Content;
			Excerpt.RichText = StoredExcerpts[ Index ].RichText;
			return true;
		}
	}

	return false;
}

bool UAssetBrowserDOC::FExtDocumentationPage::HasExcerpt( const FString& ExcerptName )
{
	return StoredMetadata.ExcerptNames.Contains( ExcerptName );
}

int32 UAssetBrowserDOC::FExtDocumentationPage::GetNumExcerpts() const
{
	return StoredExcerpts.Num();
}

bool UAssetBrowserDOC::FExtDocumentationPage::GetExcerpt(const FString& ExcerptName, FExcerpt& Excerpt)
{
	for (const FExcerpt& StoredExcerpt : StoredExcerpts)
	{
		if (StoredExcerpt.Name == ExcerptName)
		{
			Excerpt = StoredExcerpt;
			return true;
		}
	}

	return false;
}

void UAssetBrowserDOC::FExtDocumentationPage::GetExcerpts( /*OUT*/ TArray< FExcerpt >& Excerpts )
{
	Excerpts.Empty();
	for (int32 i = 0; i < StoredExcerpts.Num(); ++i)
	{
		Excerpts.Add(StoredExcerpts[i]);
	}
}

FText UAssetBrowserDOC::FExtDocumentationPage::GetTitle()
{
	return StoredMetadata.Title;
}

void UAssetBrowserDOC::FExtDocumentationPage::Reload()
{
	StoredExcerpts.Empty();
	StoredMetadata = FUDNPageMetadata();
	Parser->Parse( Link, StoredExcerpts, StoredMetadata );
}

void UAssetBrowserDOC::FExtDocumentationPage::SetTextWrapAt( TAttribute<float> WrapAt )
{
	Parser->SetWrapAt( WrapAt );
}

bool UAssetBrowserDOC::FExtDocumentationPage::GetSimpleExcerptContent(FExcerpt& Excerpt)
{
	for (int32 Index = 0; Index < StoredExcerpts.Num(); ++Index)
	{
		if (Excerpt.Name == StoredExcerpts[Index].Name)
		{
			Parser->GetExcerptContent(Link, StoredExcerpts[Index], /*bInSimpleText*/ true);
			Excerpt.Content = StoredExcerpts[Index].Content;
			Excerpt.RichText = StoredExcerpts[Index].RichText;
			return true;
		}
	}

	return false;
}

UAssetBrowserDOC::FExtDocumentationPage::FExtDocumentationPage( const FString& InLink, const TSharedRef< FExtUDNParser >& InParser )
	: Link( InLink )
	, Parser( InParser )
{
	Parser->Parse( Link, StoredExcerpts, StoredMetadata );
}
