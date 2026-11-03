#include "BlueprintComponentToolsBPLibrary.h"
#include "GameFramework/Actor.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"

#if WITH_EDITOR
#include "Editor.h"
#endif

TArray<UBlueprintComponentToolsBPLibrary::FBindItem> UBlueprintComponentToolsBPLibrary::BindList;

bool UBlueprintComponentToolsBPLibrary::AddSkeletalMeshComponentToActor(AActor* TargetActor, USkeletalMesh* SkeletalMesh)
{
#if WITH_EDITOR
	if (!TargetActor) return false;

	USkeletalMeshComponent* NewComp = NewObject<USkeletalMeshComponent>(TargetActor);
	if (!NewComp) return false;

	if (SkeletalMesh)
		NewComp->SetSkeletalMesh(SkeletalMesh);

	if (TargetActor->GetRootComponent())
	{
		NewComp->AttachToComponent(TargetActor->GetRootComponent(), FAttachmentTransformRules::KeepRelativeTransform);
	}

	NewComp->RegisterComponent();
	TargetActor->AddInstanceComponent(NewComp);
	TargetActor->AddOwnedComponent(NewComp);
	TargetActor->Modify();
	TargetActor->RerunConstructionScripts();
	return true;
#else
	return false;
#endif
}

void UBlueprintComponentToolsBPLibrary::BindWatchActorDelete(AActor* WatchTarget, UObject* CallbackTarget, FName FunctionName)
{
#if WITH_EDITOR
	if (!WatchTarget || !CallbackTarget || FunctionName.IsNone())
		return;

	// ====================== 核心：自动去重 ======================
	// 同一个 监听目标 + 回调者 只能存在一个，重复调用会自动覆盖
	for (int i = BindList.Num() - 1; i >= 0; --i)
	{
		const auto& Item = BindList[i];
		if (Item.Target == WatchTarget && Item.CallbackObj == CallbackTarget)
		{
			BindList.RemoveAt(i);
		}
	}

	// 添加新绑定
	FBindItem Item;
	Item.Target = WatchTarget;
	Item.CallbackObj = CallbackTarget;
	Item.FuncName = FunctionName;
	BindList.Add(Item);

	// 只注册一次定时器
	static bool bTickerAdded = false;
	if (!bTickerAdded)
	{
		bTickerAdded = true;
		FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateLambda([](float)
			{
				CheckDeleted();
				return true;
			}), 0.2f);
	}
#endif
}

void UBlueprintComponentToolsBPLibrary::CheckDeleted()
{
#if WITH_EDITOR
	for (int i = BindList.Num() - 1; i >= 0; --i)
	{
		auto& Item = BindList[i];
		if (!Item.Target.IsValid())
		{
			if (Item.CallbackObj.IsValid() && !Item.FuncName.IsNone())
			{
				UFunction* Func = Item.CallbackObj->FindFunction(Item.FuncName);
				if (Func)
				{
					Item.CallbackObj->ProcessEvent(Func, nullptr);
				}
			}
			BindList.RemoveAt(i);
		}
	}
#endif
}