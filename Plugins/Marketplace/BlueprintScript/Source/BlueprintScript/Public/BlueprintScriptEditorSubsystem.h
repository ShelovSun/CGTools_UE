// BlueprintScriptEditorSubsystem.h

#pragma once

#include "CoreMinimal.h"
#include "EditorSubsystem.h"
#include "Containers/Ticker.h"
#include "Delegates/DelegateCombinations.h"

#include "BlueprintScriptEditorSubsystem.generated.h"

///////////////////////////////////////////////////////////
// Delegates
///////////////////////////////////////////////////////////

DECLARE_DYNAMIC_MULTICAST_DELEGATE(
	FOnEditorReady
);

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(
	FOnLeftMouseClicked,
	FVector,
	WorldOrigin,
	FVector,
	WorldDirection
);

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(
	FOnRightMouseClicked,
	FVector,
	WorldOrigin,
	FVector,
	WorldDirection
);

// NEW: 鼠标松开委托
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(
	FOnLeftMouseReleased,
	FVector,
	WorldOrigin,
	FVector,
	WorldDirection
);

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(
	FOnRightMouseReleased,
	FVector,
	WorldOrigin,
	FVector,
	WorldDirection
);

// NEW: Enter按下委托
DECLARE_DYNAMIC_MULTICAST_DELEGATE(
	FOnEnterKeyPressed
);

///////////////////////////////////////////////////////////
// Subsystem
///////////////////////////////////////////////////////////

UCLASS()
class BLUEPRINTSCRIPT_API
	UBlueprintScriptEditorSubsystem
	: public UEditorSubsystem
{
	GENERATED_BODY()

public:

	virtual void Initialize(
		FSubsystemCollectionBase& Collection
	) override;

	virtual void Deinitialize() override;

	///////////////////////////////////////////////////////////
	// Editor Ready
	///////////////////////////////////////////////////////////

	UPROPERTY(BlueprintAssignable)
	FOnEditorReady OnEditorReady;

	UFUNCTION(BlueprintCallable, Category = "BlueprintScript")
	bool IsEditorReady() const;

	///////////////////////////////////////////////////////////
	// Mouse Events
	///////////////////////////////////////////////////////////

	UPROPERTY(BlueprintAssignable)
	FOnLeftMouseClicked OnLeftMouseClicked;

	UPROPERTY(BlueprintAssignable)
	FOnRightMouseClicked OnRightMouseClicked;

	// NEW: 鼠标松开事件
	UPROPERTY(BlueprintAssignable)
	FOnLeftMouseReleased OnLeftMouseReleased;

	UPROPERTY(BlueprintAssignable)
	FOnRightMouseReleased OnRightMouseReleased;

	// NEW: Enter按下事件
	UPROPERTY(BlueprintAssignable)
	FOnEnterKeyPressed OnEnterKeyPressed;

	///////////////////////////////////////////////////////////
	// Keyboard State
	///////////////////////////////////////////////////////////

	UFUNCTION(BlueprintCallable, Category = "BlueprintScript")
	bool IsCtrlPressed() const;

	UFUNCTION(BlueprintCallable, Category = "BlueprintScript")
	bool IsShiftPressed() const;

	UFUNCTION(BlueprintCallable, Category = "BlueprintScript")
	bool IsAltPressed() const;

	///////////////////////////////////////////////////////////
	// Mouse State
	///////////////////////////////////////////////////////////

	UFUNCTION(BlueprintCallable, Category = "BlueprintScript")
	bool IsLeftMouseDown() const;

	UFUNCTION(BlueprintCallable, Category = "BlueprintScript")
	bool IsRightMouseDown() const;

	// NEW: 清除所有绑定事件
	UFUNCTION(BlueprintCallable, Category = "Input")
	void ClearAllBindings();


	UFUNCTION(BlueprintCallable, Category = "Input")
	void ClearBindings(UObject* Listener);
private:

	TSharedPtr<class FBlueprintScriptInputProcessor>
		InputProcessor;

	bool bEditorReady = false;

	FTSTicker::FDelegateHandle TickHandle;

public:

	UFUNCTION(BlueprintCallable, Category = "Editor|Rendering")
	void SetCustomDepthStencil(int32 Value);
};