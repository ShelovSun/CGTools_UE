#include "CrowdMigrationDialog.h"
#include "CrowdProjectMigrator.h"

#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Views/STreeView.h"
#include "Widgets/Views/STableRow.h"
#include "Styling/AppStyle.h"

#define LOCTEXT_NAMESPACE "CrowdMigrationDialog"

void SCrowdMigrationDialog::Construct(const FArguments& InArgs)
{
	SourceAssets = InArgs._Assets;
	BuildTree();

	ChildSlot
	[
		SNew(SVerticalBox)

		// 顶部：目标子目录输入 + 仅预览勾选
		+ SVerticalBox::Slot().AutoHeight().Padding(8, 8, 8, 2)
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 6, 0)
			[
				SNew(STextBlock).Text(FText::FromString(TEXT("目标子目录（留空=保持原 /Game/ 路径）：")))
			]
			+ SHorizontalBox::Slot().FillWidth(1.0f).MaxWidth(360).VAlign(VAlign_Center)
			[
				SNew(SEditableTextBox)
				.HintText(FText::FromString(TEXT("例如 Imported/hrw")))
				.Text(this, &SCrowdMigrationDialog::GetDestSubPathText)
				.OnTextChanged(this, &SCrowdMigrationDialog::OnDestSubPathTextChanged)
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(12, 0, 0, 0)
			[
				SNew(SCheckBox)
				.IsChecked(this, &SCrowdMigrationDialog::GetPreviewChecked)
				.OnCheckStateChanged(this, &SCrowdMigrationDialog::OnPreviewChecked)
				.Content()
				[
					SNew(STextBlock).Text(FText::FromString(TEXT("仅预览（不复制文件）")))
				]
			]
		]

		// 顶部：统计 + 快捷操作
		+ SVerticalBox::Slot().AutoHeight().Padding(8, 4, 8, 4)
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
			[
				SNew(STextBlock).Text(FText::FromString(
					FString::Printf(TEXT("共 %d 个资产，其中冲突 %d 个。勾选表示覆盖目标中已存在的同名文件。"),
						SourceAssets->Num(), CountConflicts())))
			]
			+ SHorizontalBox::Slot().FillWidth(1.0f)
			+ SHorizontalBox::Slot().AutoWidth().Padding(4, 0, 0, 0)
			[
				SNew(SButton).Text(FText::FromString(TEXT("全部覆盖"))).OnClicked(this, &SCrowdMigrationDialog::OnOverwriteAll)
			]
			+ SHorizontalBox::Slot().AutoWidth().Padding(4, 0, 0, 0)
			[
				SNew(SButton).Text(FText::FromString(TEXT("全部不覆盖"))).OnClicked(this, &SCrowdMigrationDialog::OnOverwriteNone)
			]
			+ SHorizontalBox::Slot().AutoWidth().Padding(4, 0, 0, 0)
			[
				SNew(SButton).Text(FText::FromString(TEXT("仅覆盖冲突"))).OnClicked(this, &SCrowdMigrationDialog::OnOverwriteConflictsOnly)
			]
		]

		// 中部：资产树
		+ SVerticalBox::Slot().FillHeight(1.0f).Padding(8, 4, 8, 4)
		[
			SNew(SBorder).BorderImage(FAppStyle::Get().GetBrush("ToolPanel.GroupBorder"))
			[
				SAssignNew(TreeView, STreeView<TSharedPtr<FCrowdMigrationTreeNode>>)
				.TreeItemsSource(&TreeItems)
				.OnGenerateRow(this, &SCrowdMigrationDialog::OnGenerateRow)
				.OnGetChildren(this, &SCrowdMigrationDialog::OnGetChildren)
				.ClearSelectionOnClick(false)
			]
		]

		// 底部：取消 / 确认
		+ SVerticalBox::Slot().AutoHeight().Padding(8, 4, 8, 8)
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().FillWidth(1.0f)
			+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 8, 0)
			[
				SNew(SButton).Text(FText::FromString(TEXT("取消"))).OnClicked(this, &SCrowdMigrationDialog::OnCancel)
			]
			+ SHorizontalBox::Slot().AutoWidth()
			[
				SNew(SButton).Text(FText::FromString(TEXT("确认迁移"))).OnClicked(this, &SCrowdMigrationDialog::OnConfirm)
			]
		]
	];

	if (TreeView.IsValid())
	{
		TreeView->RequestTreeRefresh();
		// 默认全部展开，方便用户看到所有子文件夹和子资产
		ExpandAll(RootNode);
	}
}

void SCrowdMigrationDialog::ExpandAll(TSharedPtr<FCrowdMigrationTreeNode> Node)
{
	if (Node.IsValid() && TreeView.IsValid() && Node->Children.Num() > 0)
	{
		TreeView->SetItemExpansion(Node, true);
		for (const TSharedPtr<FCrowdMigrationTreeNode>& Child : Node->Children)
		{
			ExpandAll(Child);
		}
	}
}

void SCrowdMigrationDialog::CountFolder(TSharedPtr<FCrowdMigrationTreeNode> Node, int32& OutConflicts, int32& OutTotal) const
{
	if (Node->Asset)
	{
		OutTotal++;
		if (Node->Asset->bConflict)
		{
			OutConflicts++;
		}
	}
	for (const auto& C : Node->Children)
	{
		CountFolder(C, OutConflicts, OutTotal);
	}
}

void SCrowdMigrationDialog::BuildTree()
{
	RootNode = MakeShared<FCrowdMigrationTreeNode>();

	for (FCrowdMigrationAsset& A : *SourceAssets)
	{
		// RelativePath 内部用的是反斜杠（\），所以按 \ 和 / 都拆一下以兼容。
		FString Normalized = A.RelativePath;
		Normalized.ReplaceInline(TEXT("\\"), TEXT("/"));

		TArray<FString> Parts;
		Normalized.ParseIntoArray(Parts, TEXT("/"), true);

		TSharedPtr<FCrowdMigrationTreeNode> Cur = RootNode;
		for (int32 i = 0; i < Parts.Num() - 1; i++)
		{
			Cur = FindOrAddChild(Cur, Parts[i]);
		}

		TSharedPtr<FCrowdMigrationTreeNode> Leaf = MakeShared<FCrowdMigrationTreeNode>();
		Leaf->Name = Parts.Last();
		Leaf->Asset = &A;
		Cur->Children.Add(Leaf);
	}

	TreeItems = RootNode->Children;
}

TSharedPtr<FCrowdMigrationTreeNode> SCrowdMigrationDialog::FindOrAddChild(TSharedPtr<FCrowdMigrationTreeNode> Parent, const FString& Name)
{
	for (auto& C : Parent->Children)
	{
		if (C->Name == Name)
		{
			return C;
		}
	}
	TSharedPtr<FCrowdMigrationTreeNode> NewChild = MakeShared<FCrowdMigrationTreeNode>();
	NewChild->Name = Name;
	NewChild->bIsFolder = true;
	Parent->Children.Add(NewChild);
	return NewChild;
}

void SCrowdMigrationDialog::ForEachAsset(TSharedPtr<FCrowdMigrationTreeNode> Node, TFunction<void(FCrowdMigrationAsset&)>&& Fn)
{
	if (Node->Asset)
	{
		Fn(*Node->Asset);
	}
	for (auto& C : Node->Children)
	{
		ForEachAsset(C, MoveTemp(Fn));
	}
}

TSharedRef<ITableRow> SCrowdMigrationDialog::OnGenerateRow(TSharedPtr<FCrowdMigrationTreeNode> Item, const TSharedRef<STableViewBase>& Owner)
{
	TSharedRef<SHorizontalBox> HB = SNew(SHorizontalBox);

	if (Item->bIsFolder)
	{
		// 统计本文件夹下"冲突数 / 总数"，让用户一眼看清结构。
		int32 Conflicts = 0, Total = 0;
		CountFolder(Item, Conflicts, Total);

		HB->AddSlot().AutoWidth().Padding(0, 0, 4, 0)
		[
			SNew(SCheckBox)
			.IsChecked(this, &SCrowdMigrationDialog::GetFolderCheck, Item)
			.OnCheckStateChanged(this, &SCrowdMigrationDialog::OnFolderCheck, Item)
		];
		HB->AddSlot().AutoWidth()
		[
			SNew(STextBlock)
			.Text(FText::FromString(
				FString::Printf(TEXT("%s  [冲突 %d / %d]"), *Item->Name, Conflicts, Total)))
			.Font(FAppStyle::Get().GetFontStyle("BoldFont"))
			.ColorAndOpacity(Conflicts > 0 ? FLinearColor(1.0f, 0.65f, 0.0f) : FLinearColor::Gray)
		];
	}
	else
	{
		FCrowdMigrationAsset* A = Item->Asset;
		if (A && A->bConflict)
		{
			HB->AddSlot().AutoWidth().Padding(0, 0, 4, 0)
			[
				SNew(SCheckBox)
				.IsChecked(this, &SCrowdMigrationDialog::GetAssetCheck, A)
				.OnCheckStateChanged(this, &SCrowdMigrationDialog::OnAssetCheck, A)
			];
			HB->AddSlot().AutoWidth().Padding(2, 0, 0, 0)
			[
				SNew(STextBlock).Text(FText::FromString(A->RelativePath)).ColorAndOpacity(FLinearColor::Red)
			];
			HB->AddSlot().AutoWidth().Padding(6, 0, 0, 0)
			[
				SNew(STextBlock).Text(FText::FromString(TEXT("冲突"))).ColorAndOpacity(FLinearColor::Red)
			];
		}
		else
		{
			HB->AddSlot().AutoWidth().Padding(22, 0, 0, 0)
			[
				SNew(STextBlock).Text(FText::FromString(A ? A->RelativePath : Item->Name))
			];
			HB->AddSlot().AutoWidth().Padding(6, 0, 0, 0)
			[
				SNew(STextBlock).Text(FText::FromString(TEXT("新增"))).ColorAndOpacity(FLinearColor::Green)
			];
		}
	}

	TSharedRef<STableRow<TSharedPtr<FCrowdMigrationTreeNode>>> Row =
		SNew(STableRow<TSharedPtr<FCrowdMigrationTreeNode>>, Owner)
		[
			HB
		];

	if (Item->Asset)
	{
		Row->SetToolTipText(FText::FromString(Item->Asset->SourceFile + TEXT("\n→ ") + Item->Asset->DestFile));
	}
	return Row;
}

void SCrowdMigrationDialog::OnGetChildren(TSharedPtr<FCrowdMigrationTreeNode> Item, TArray<TSharedPtr<FCrowdMigrationTreeNode>>& Out)
{
	Out = Item->Children;
}

ECheckBoxState SCrowdMigrationDialog::GetFolderCheck(TSharedPtr<FCrowdMigrationTreeNode> Folder) const
{
	// 三态：所有冲突项都覆盖→Checked；都没覆盖→Unchecked；混合→Undetermined
	int32 Checked = 0, Conflicts = 0;
	const_cast<SCrowdMigrationDialog*>(this)->ForEachAsset(Folder, [&](FCrowdMigrationAsset& A)
	{
		if (A.bConflict)
		{
			Conflicts++;
			if (A.bOverwrite)
			{
				Checked++;
			}
		}
	});
	if (Conflicts == 0)
	{
		return ECheckBoxState::Unchecked;
	}
	if (Checked == Conflicts)
	{
		return ECheckBoxState::Checked;
	}
	if (Checked == 0)
	{
		return ECheckBoxState::Unchecked;
	}
	return ECheckBoxState::Undetermined;
}

void SCrowdMigrationDialog::OnFolderCheck(ECheckBoxState State, TSharedPtr<FCrowdMigrationTreeNode> Folder)
{
	const bool bVal = (State == ECheckBoxState::Checked);
	ForEachAsset(Folder, [bVal](FCrowdMigrationAsset& A)
	{
		if (A.bConflict)
		{
			A.bOverwrite = bVal;
		}
	});
	if (TreeView.IsValid())
	{
		TreeView->RequestTreeRefresh();
	}
}

ECheckBoxState SCrowdMigrationDialog::GetAssetCheck(FCrowdMigrationAsset* Asset) const
{
	return (Asset && Asset->bOverwrite) ? ECheckBoxState::Checked : ECheckBoxState::Unchecked;
}

void SCrowdMigrationDialog::OnAssetCheck(ECheckBoxState State, FCrowdMigrationAsset* Asset)
{
	if (Asset)
	{
		Asset->bOverwrite = (State == ECheckBoxState::Checked);
	}
	if (TreeView.IsValid())
	{
		TreeView->RequestTreeRefresh();
	}
}

FReply SCrowdMigrationDialog::OnOverwriteAll()
{
	for (FCrowdMigrationAsset& A : *SourceAssets)
	{
		A.bOverwrite = true;
	}
	if (TreeView.IsValid())
	{
		TreeView->RequestTreeRefresh();
	}
	return FReply::Handled();
}

FReply SCrowdMigrationDialog::OnOverwriteNone()
{
	for (FCrowdMigrationAsset& A : *SourceAssets)
	{
		A.bOverwrite = false;
	}
	if (TreeView.IsValid())
	{
		TreeView->RequestTreeRefresh();
	}
	return FReply::Handled();
}

FReply SCrowdMigrationDialog::OnOverwriteConflictsOnly()
{
	for (FCrowdMigrationAsset& A : *SourceAssets)
	{
		A.bOverwrite = A.bConflict;
	}
	if (TreeView.IsValid())
	{
		TreeView->RequestTreeRefresh();
	}
	return FReply::Handled();
}

FReply SCrowdMigrationDialog::OnConfirm()
{
	bConfirmed = true;
	if (OwnerWindow.IsValid())
	{
		OwnerWindow.Pin()->RequestDestroyWindow();
	}
	return FReply::Handled();
}

FReply SCrowdMigrationDialog::OnCancel()
{
	bConfirmed = false;
	if (OwnerWindow.IsValid())
	{
		OwnerWindow.Pin()->RequestDestroyWindow();
	}
	return FReply::Handled();
}

int32 SCrowdMigrationDialog::CountConflicts() const
{
	int32 C = 0;
	for (const FCrowdMigrationAsset& A : *SourceAssets)
	{
		if (A.bConflict)
		{
			C++;
		}
	}
	return C;
}

#undef LOCTEXT_NAMESPACE
