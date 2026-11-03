// BlueprintScriptInputProcessor.cpp

#include "BlueprintScriptInputProcessor.h"
#include "BlueprintScriptEditorSubsystem.h"

#include "Framework/Application/SlateApplication.h"
#include "InputCoreTypes.h"
#include "Editor.h"
#include "EditorViewportClient.h"
#include "SceneView.h"

bool FBlueprintScriptInputProcessor::bCtrlDown = false;
bool FBlueprintScriptInputProcessor::bShiftDown = false;
bool FBlueprintScriptInputProcessor::bAltDown = false;

bool FBlueprintScriptInputProcessor::bLeftMouseDown = false;
bool FBlueprintScriptInputProcessor::bRightMouseDown = false;

void FBlueprintScriptInputProcessor::SetSubsystem(
	UBlueprintScriptEditorSubsystem* InSubsystem)
{
	Subsystem = InSubsystem;
}

void FBlueprintScriptInputProcessor::Tick(
	const float DeltaTime,
	FSlateApplication& SlateApp,
	TSharedRef<ICursor> Cursor)
{
}

bool FBlueprintScriptInputProcessor::HandleKeyDownEvent(
	FSlateApplication& SlateApp,
	const FKeyEvent& InKeyEvent)
{
	// ==============================================
	// PIE 运行时禁用所有输入处理
	// ==============================================
	if (GEditor && GEditor->IsPlaySessionInProgress())
	{
		return false;
	}

	// 监听 左Ctrl + 右Ctrl
	if (InKeyEvent.GetKey() == EKeys::LeftControl || InKeyEvent.GetKey() == EKeys::RightControl)
	{
		bCtrlDown = true;
	}

	if (InKeyEvent.GetKey() == EKeys::LeftShift || InKeyEvent.GetKey() == EKeys::RightShift)
	{
		bShiftDown = true;
	}

	if (InKeyEvent.GetKey() == EKeys::LeftAlt)
	{
		bAltDown = true;
	}

	// NEW: Enter 键按下
	if (InKeyEvent.GetKey() == EKeys::Enter && Subsystem)
	{
		Subsystem->OnEnterKeyPressed.Broadcast();
	}

	return false;
}

bool FBlueprintScriptInputProcessor::HandleKeyUpEvent(
	FSlateApplication& SlateApp,
	const FKeyEvent& InKeyEvent)
{
	// ==============================================
	// PIE 运行时禁用所有输入处理
	// ==============================================
	if (GEditor && GEditor->IsPlaySessionInProgress())
	{
		return false;
	}



	// 左Ctrl / 右Ctrl 抬起
	if (InKeyEvent.GetKey() == EKeys::LeftControl || InKeyEvent.GetKey() == EKeys::RightControl)
	{
		bCtrlDown = false;
	}


	// 左Shift / 右Shift 抬起
	if (InKeyEvent.GetKey() == EKeys::LeftShift || InKeyEvent.GetKey() == EKeys::RightShift)
	{
		bShiftDown = false;
	}


	if (InKeyEvent.GetKey() == EKeys::LeftAlt)
	{
		bAltDown = false;
	}

	return false;
}

bool FBlueprintScriptInputProcessor::HandleMouseButtonDownEvent(
	FSlateApplication& SlateApp,
	const FPointerEvent& MouseEvent)
{
	// ==============================================
	// PIE 运行时禁用所有输入处理
	// ==============================================
	if (GEditor && GEditor->IsPlaySessionInProgress())
	{
		return false;
	}

	FVector RayOrigin;
	FVector RayDirection;

	bool bHasRay =
		GetViewportRay(
			RayOrigin,
			RayDirection
		);

	if (MouseEvent.GetEffectingButton() ==
		EKeys::LeftMouseButton)
	{
		bLeftMouseDown = true;

		if (Subsystem && bHasRay)
		{
			Subsystem->OnLeftMouseClicked.Broadcast(
				RayOrigin,
				RayDirection
			);
		}
	}

	if (MouseEvent.GetEffectingButton() ==
		EKeys::RightMouseButton)
	{
		bRightMouseDown = true;

		if (Subsystem && bHasRay)
		{
			Subsystem->OnRightMouseClicked.Broadcast(
				RayOrigin,
				RayDirection
			);
		}
	}

	return false;
}

bool FBlueprintScriptInputProcessor::HandleMouseButtonUpEvent(
	FSlateApplication& SlateApp,
	const FPointerEvent& MouseEvent)
{
	// ==============================================
	// PIE 运行时禁用所有输入处理
	// ==============================================
	if (GEditor && GEditor->IsPlaySessionInProgress())
	{
		return false;
	}

	FVector RayOrigin;
	FVector RayDirection;
	bool bHasRay = GetViewportRay(RayOrigin, RayDirection);

	if (MouseEvent.GetEffectingButton() == EKeys::LeftMouseButton)
	{
		bLeftMouseDown = false;

		// NEW: 左键松开广播
		if (Subsystem && bHasRay)
		{
			Subsystem->OnLeftMouseReleased.Broadcast(RayOrigin, RayDirection);
		}
	}

	if (MouseEvent.GetEffectingButton() == EKeys::RightMouseButton)
	{
		bRightMouseDown = false;

		// NEW: 右键松开广播
		if (Subsystem && bHasRay)
		{
			Subsystem->OnRightMouseReleased.Broadcast(RayOrigin, RayDirection);
		}
	}

	return false;
}

bool FBlueprintScriptInputProcessor::GetViewportRay(
	FVector& OutOrigin,
	FVector& OutDirection)
{
	if (!GEditor)
	{
		return false;
	}

	FViewport* Viewport =
		GEditor->GetActiveViewport();

	if (!Viewport)
	{
		return false;
	}

	FEditorViewportClient* ViewportClient =
		static_cast<FEditorViewportClient*>(
			Viewport->GetClient()
			);

	if (!ViewportClient)
	{
		return false;
	}

	FSceneViewFamilyContext ViewFamily(
		FSceneViewFamily::ConstructionValues(
			Viewport,
			ViewportClient->GetScene(),
			ViewportClient->EngineShowFlags
		)
	);

	FSceneView* SceneView =
		ViewportClient->CalcSceneView(
			&ViewFamily
		);

	if (!SceneView)
	{
		return false;
	}

	FIntPoint MousePosition;

	Viewport->GetMousePos(MousePosition);

	SceneView->DeprojectFVector2D(
		FVector2D(MousePosition),
		OutOrigin,
		OutDirection
	);

	return true;
}