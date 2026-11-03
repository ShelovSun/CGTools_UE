#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/Views/STreeView.h"

struct FCrowdMigrationAsset;

/** 冲突对话框的树节点：文件夹节点或资产叶子节点。 */
class FCrowdMigrationTreeNode : public TSharedFromThis<FCrowdMigrationTreeNode>
{
public:
	FString Name;
	bool bIsFolder = false;
	FCrowdMigrationAsset* Asset = nullptr; // 仅叶子节点有效，直接指向原始清单元素
	TArray<TSharedPtr<FCrowdMigrationTreeNode>> Children;
};

/**
 * 迁移前的冲突确认弹窗（模态）。
 * - 树形展示：文件夹 -> 子文件夹 -> 资产。
 * - 冲突资产标红并提供"覆盖"勾选框；非冲突资产标记为"新增"。
 * - 文件夹上的勾选框可批量设置其下所有冲突资产的覆盖选择（三态）。
 * - 顶部快捷按钮：全部覆盖 / 全部不覆盖 / 仅覆盖冲突。
 */
class SCrowdMigrationDialog : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SCrowdMigrationDialog) {}
		SLATE_ARGUMENT(TArray<FCrowdMigrationAsset>*, Assets)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);

	bool WasConfirmed() const { return bConfirmed; }

	/** 用户在弹窗中填写的目标子目录（回传给主流程）。 */
	FString DestinationSubPath;
	/** 用户是否勾选"仅预览（不复制）"。 */
	bool bPreviewOnly = false;

	TWeakPtr<SWindow> OwnerWindow;

private:
	TArray<FCrowdMigrationAsset>* SourceAssets = nullptr;
	TSharedPtr<FCrowdMigrationTreeNode> RootNode;
	TArray<TSharedPtr<FCrowdMigrationTreeNode>> TreeItems;
	TSharedPtr<STreeView<TSharedPtr<FCrowdMigrationTreeNode>>> TreeView;
	bool bConfirmed = false;

	void BuildTree();
	TSharedPtr<FCrowdMigrationTreeNode> FindOrAddChild(TSharedPtr<FCrowdMigrationTreeNode> Parent, const FString& Name);
	void ForEachAsset(TSharedPtr<FCrowdMigrationTreeNode> Node, TFunction<void(FCrowdMigrationAsset&)>&& Fn);
	/** 递归展开所有有子项的节点，让用户能直接看到所有层级的冲突项。 */
	void ExpandAll(TSharedPtr<FCrowdMigrationTreeNode> Node);
	/** 递归统计指定节点下"冲突"和"总数"。 */
	void CountFolder(TSharedPtr<FCrowdMigrationTreeNode> Node, int32& OutConflicts, int32& OutTotal) const;

	TSharedRef<ITableRow> OnGenerateRow(TSharedPtr<FCrowdMigrationTreeNode> Item, const TSharedRef<STableViewBase>& Owner);
	void OnGetChildren(TSharedPtr<FCrowdMigrationTreeNode> Item, TArray<TSharedPtr<FCrowdMigrationTreeNode>>& Out);

	ECheckBoxState GetFolderCheck(TSharedPtr<FCrowdMigrationTreeNode> Folder) const;
	void OnFolderCheck(ECheckBoxState State, TSharedPtr<FCrowdMigrationTreeNode> Folder);
	ECheckBoxState GetAssetCheck(FCrowdMigrationAsset* Asset) const;
	void OnAssetCheck(ECheckBoxState State, FCrowdMigrationAsset* Asset);

	FReply OnConfirm();
	FReply OnCancel();
	FReply OnOverwriteAll();
	FReply OnOverwriteNone();
	FReply OnOverwriteConflictsOnly();

	// 目标子目录输入框的读写。
	FText GetDestSubPathText() const { return FText::FromString(DestinationSubPath); }
	void OnDestSubPathTextChanged(const FText& InText) { DestinationSubPath = InText.ToString(); }
	// 仅预览勾选框的读写。
	ECheckBoxState GetPreviewChecked() const { return bPreviewOnly ? ECheckBoxState::Checked : ECheckBoxState::Unchecked; }
	void OnPreviewChecked(ECheckBoxState InState) { bPreviewOnly = (InState == ECheckBoxState::Checked); }

	int32 CountConflicts() const;
};
