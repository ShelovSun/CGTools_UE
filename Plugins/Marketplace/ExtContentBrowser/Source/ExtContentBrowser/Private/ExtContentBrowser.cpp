// Copyright 2017-2021 marynate. All Rights Reserved.

#include "ExtContentBrowser.h"
#include "ExtContentBrowserSingleton.h"

#include "LevelEditor.h"
#include "Widgets/Docking/SDockTab.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Text/STextBlock.h"
#include "Framework/MultiBox/MultiBoxBuilder.h"

#include "ExtDocumentation.h"

DEFINE_LOG_CATEGORY(LogECB);

#define LOCTEXT_NAMESPACE "ExtContentBrowser"

/////////////////////////////////////////////////////////////
// FExtContentBrowserModule implementation
//

void FExtContentBrowserModule::StartupModule()
{
	ContentBrowserSingleton = new FExtContentBrowserSingleton();

	// Documentation
	UAssetBrowserDOC::FExtDocumentationStyle::Initialize();
	Documentation = UAssetBrowserDOC::FExtDocumentation::Create();
	UAssetBrowserDOC::FDocumentationProvider::Get().RegisterProvider(*UAssetBrowserDOC::DocumentationHostPluginName, this);
}

void FExtContentBrowserModule::ShutdownModule()
{
	if (ContentBrowserSingleton)
	{
		delete ContentBrowserSingleton;
		ContentBrowserSingleton = NULL;
	}

	// Documentation
	UAssetBrowserDOC::FExtDocumentationStyle::Shutdown();
}

IExtContentBrowserSingleton& FExtContentBrowserModule::Get() const
{
	check(ContentBrowserSingleton);
	return *ContentBrowserSingleton;
}

TSharedRef<IDocumentation> FExtContentBrowserModule::GetDocumentation() const
{
	return Documentation.ToSharedRef();
}

#undef LOCTEXT_NAMESPACE
	
IMPLEMENT_MODULE(FExtContentBrowserModule, ExtContentBrowser)
