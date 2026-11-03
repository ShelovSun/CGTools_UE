#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "BlueprintComponentToolsBPLibrary.generated.h"

class AActor;
class USkeletalMesh;

UCLASS()
class BLUEPRINTCOMPONENTTOOLS_API UBlueprintComponentToolsBPLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	UFUNCTION(BlueprintCallable, Category = "Blueprint Component Tools")
	static bool AddSkeletalMeshComponentToActor(AActor* TargetActor, USkeletalMesh* SkeletalMesh);

	UFUNCTION(BlueprintCallable, Category = "Blueprint Component Tools|Editor", meta = (DevelopmentOnly))
	static void BindWatchActorDelete(AActor* WatchTarget, UObject* CallbackTarget, FName FunctionName);

private:
	struct FBindItem
	{
		TWeakObjectPtr<AActor> Target;
		TWeakObjectPtr<UObject> CallbackObj;
		FName FuncName;
	};

	static TArray<FBindItem> BindList;
	static void CheckDeleted();
};