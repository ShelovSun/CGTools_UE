// BlueprintScriptInputProcessor.h

#pragma once

#include "CoreMinimal.h"
#include "Framework/Application/IInputProcessor.h"

class UBlueprintScriptEditorSubsystem;

class FBlueprintScriptInputProcessor
	: public IInputProcessor
{
public:

	virtual void Tick(
		const float DeltaTime,
		FSlateApplication& SlateApp,
		TSharedRef<ICursor> Cursor
	) override;

	virtual bool HandleKeyDownEvent(
		FSlateApplication& SlateApp,
		const FKeyEvent& InKeyEvent
	) override;

	virtual bool HandleKeyUpEvent(
		FSlateApplication& SlateApp,
		const FKeyEvent& InKeyEvent
	) override;

	virtual bool HandleMouseButtonDownEvent(
		FSlateApplication& SlateApp,
		const FPointerEvent& MouseEvent
	) override;

	virtual bool HandleMouseButtonUpEvent(
		FSlateApplication& SlateApp,
		const FPointerEvent& MouseEvent
	) override;

	void SetSubsystem(
		UBlueprintScriptEditorSubsystem* InSubsystem
	);

	bool GetViewportRay(
		FVector& OutOrigin,
		FVector& OutDirection
	);

public:

	static bool bCtrlDown;
	static bool bShiftDown;
	static bool bAltDown;

	static bool bLeftMouseDown;
	static bool bRightMouseDown;

private:

	UBlueprintScriptEditorSubsystem*
		Subsystem = nullptr;
};