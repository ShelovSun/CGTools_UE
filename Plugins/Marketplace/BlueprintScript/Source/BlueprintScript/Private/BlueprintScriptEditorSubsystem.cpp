// BlueprintScriptEditorSubsystem.cpp

#include "BlueprintScriptEditorSubsystem.h"
#include "BlueprintScriptInputProcessor.h"

#include "Misc/Paths.h"



#include "Engine/RendererSettings.h"

#include "HAL/IConsoleManager.h"
#include "Misc/ConfigCacheIni.h"
#include "Engine/Engine.h"



#include "Framework/Application/SlateApplication.h"

#include "Editor.h"

void UBlueprintScriptEditorSubsystem::Initialize(
	FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);

	///////////////////////////////////////////////////////////
	// Input Processor
	///////////////////////////////////////////////////////////

	InputProcessor =
		MakeShared<FBlueprintScriptInputProcessor>();

	InputProcessor->SetSubsystem(this);

	FSlateApplication::Get()
		.RegisterInputPreProcessor(
			InputProcessor
		);

	///////////////////////////////////////////////////////////
	// Safe Editor Ready
	///////////////////////////////////////////////////////////

	TickHandle =
		FTSTicker::GetCoreTicker().AddTicker(
			FTickerDelegate::CreateLambda(
				[this](float DeltaTime)
				{
					if (!GEditor)
					{
						return true;
					}

					UWorld* World =
						GEditor
						->GetEditorWorldContext()
						.World();

					if (!World)
					{
						return true;
					}

					if (!FSlateApplication::IsInitialized())
					{
						return true;
					}

					if (!GEditor->GetActiveViewport())
					{
						return true;
					}

					bEditorReady = true;

					OnEditorReady.Broadcast();

					UE_LOG(
						LogTemp,
						Warning,
						TEXT("Editor Ready")
					);

					return false;
				}
			)
		);
}

void UBlueprintScriptEditorSubsystem::Deinitialize()
{
	if (InputProcessor.IsValid())
	{
		FSlateApplication::Get()
			.UnregisterInputPreProcessor(
				InputProcessor
			);
	}

	if (TickHandle.IsValid())
	{
		FTSTicker::GetCoreTicker()
			.RemoveTicker(TickHandle);
	}

	Super::Deinitialize();
}

bool UBlueprintScriptEditorSubsystem::IsEditorReady() const
{
	return bEditorReady;
}

bool UBlueprintScriptEditorSubsystem::IsCtrlPressed() const
{
	return FBlueprintScriptInputProcessor::bCtrlDown;
}

bool UBlueprintScriptEditorSubsystem::IsShiftPressed() const
{
	return FBlueprintScriptInputProcessor::bShiftDown;
}

bool UBlueprintScriptEditorSubsystem::IsAltPressed() const
{
	return FBlueprintScriptInputProcessor::bAltDown;
}

bool UBlueprintScriptEditorSubsystem::IsLeftMouseDown() const
{
	return FBlueprintScriptInputProcessor::bLeftMouseDown;
}

bool UBlueprintScriptEditorSubsystem::IsRightMouseDown() const
{
	return FBlueprintScriptInputProcessor::bRightMouseDown;
}

// NEW: 清除所有绑定事件
void UBlueprintScriptEditorSubsystem::ClearAllBindings()
{
	OnEditorReady.Clear();
	OnLeftMouseClicked.Clear();
	OnRightMouseClicked.Clear();
	OnLeftMouseReleased.Clear();
	OnRightMouseReleased.Clear();
	OnEnterKeyPressed.Clear();
}


void UBlueprintScriptEditorSubsystem::ClearBindings(UObject* Listener)
{
	if (!Listener)
		return;

	OnEditorReady.RemoveAll(Listener);

	OnLeftMouseClicked.RemoveAll(Listener);
	OnRightMouseClicked.RemoveAll(Listener);

	OnLeftMouseReleased.RemoveAll(Listener);
	OnRightMouseReleased.RemoveAll(Listener);

	OnEnterKeyPressed.RemoveAll(Listener);
}

void UBlueprintScriptEditorSubsystem::SetCustomDepthStencil(int32 Value)
{
	// =========================
	// 1. 修改 Project Settings（真正持久化来源）
	// =========================
	URendererSettings* Settings = GetMutableDefault<URendererSettings>();

	if (Settings)
	{
		// ?? UE5 不同版本字段可能不同
		// 常见是 CustomDepthStencil 或 CustomDepthStencilValue
		Settings->CustomDepthStencil = static_cast<ECustomDepthStencil::Type>(Value);

		// 保存到 DefaultEngine.ini
		Settings->SaveConfig();
		Settings->UpdateDefaultConfigFile();
	}

	// =========================
	// 2. 立即应用运行时 CVAR
	// =========================
	if (IConsoleVariable* CVar =
		IConsoleManager::Get().FindConsoleVariable(TEXT("r.CustomDepth")))
	{
		CVar->Set(Value);
	}

	// =========================
	// 3. 强制刷新配置缓存
	// =========================
	GConfig->Flush(false, GEngineIni);

	// =========================
	// 4. 刷新编辑器视口
	// =========================
	if (GEditor)
	{
		GEditor->RedrawAllViewports();
	}
}