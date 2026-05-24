// Copyright Epic Games, Inc. All Rights Reserved.
/*===========================================================================
	Generated code exported from UnrealHeaderTool.
	DO NOT modify this manually! Edit the corresponding .h files instead!
===========================================================================*/

#include "UObject/GeneratedCppIncludes.h"
#include "WindowsDialogBox/Public/WindowsDialogBoxFunctionLibrary.h"
#ifdef _MSC_VER
#pragma warning (push)
#pragma warning (disable : 4883)
#endif
PRAGMA_DISABLE_DEPRECATION_WARNINGS
void EmptyLinkFunctionForGeneratedCodeWindowsDialogBoxFunctionLibrary() {}
// Cross Module References
	WINDOWSDIALOGBOX_API UEnum* Z_Construct_UEnum_WindowsDialogBox_EDialogButtonClicked();
	UPackage* Z_Construct_UPackage__Script_WindowsDialogBox();
	WINDOWSDIALOGBOX_API UEnum* Z_Construct_UEnum_WindowsDialogBox_EDialogIcon();
	WINDOWSDIALOGBOX_API UEnum* Z_Construct_UEnum_WindowsDialogBox_EDialogButtons();
	WINDOWSDIALOGBOX_API UClass* Z_Construct_UClass_UWindowsDialogBoxFunctionLibrary_NoRegister();
	WINDOWSDIALOGBOX_API UClass* Z_Construct_UClass_UWindowsDialogBoxFunctionLibrary();
	ENGINE_API UClass* Z_Construct_UClass_UBlueprintFunctionLibrary();
// End Cross Module References
	static UEnum* EDialogButtonClicked_StaticEnum()
	{
		static UEnum* Singleton = nullptr;
		if (!Singleton)
		{
			Singleton = GetStaticEnum(Z_Construct_UEnum_WindowsDialogBox_EDialogButtonClicked, Z_Construct_UPackage__Script_WindowsDialogBox(), TEXT("EDialogButtonClicked"));
		}
		return Singleton;
	}
	template<> WINDOWSDIALOGBOX_API UEnum* StaticEnum<EDialogButtonClicked>()
	{
		return EDialogButtonClicked_StaticEnum();
	}
	static FCompiledInDeferEnum Z_CompiledInDeferEnum_UEnum_EDialogButtonClicked(EDialogButtonClicked_StaticEnum, TEXT("/Script/WindowsDialogBox"), TEXT("EDialogButtonClicked"), false, nullptr, nullptr);
	uint32 Get_Z_Construct_UEnum_WindowsDialogBox_EDialogButtonClicked_Hash() { return 3270531218U; }
	UEnum* Z_Construct_UEnum_WindowsDialogBox_EDialogButtonClicked()
	{
#if WITH_HOT_RELOAD
		UPackage* Outer = Z_Construct_UPackage__Script_WindowsDialogBox();
		static UEnum* ReturnEnum = FindExistingEnumIfHotReloadOrDynamic(Outer, TEXT("EDialogButtonClicked"), 0, Get_Z_Construct_UEnum_WindowsDialogBox_EDialogButtonClicked_Hash(), false);
#else
		static UEnum* ReturnEnum = nullptr;
#endif // WITH_HOT_RELOAD
		if (!ReturnEnum)
		{
			static const UE4CodeGen_Private::FEnumeratorParam Enumerators[] = {
				{ "EDialogButtonClicked::IDNONE", (int64)EDialogButtonClicked::IDNONE },
				{ "EDialogButtonClicked::IDOK", (int64)EDialogButtonClicked::IDOK },
				{ "EDialogButtonClicked::IDCANCEL", (int64)EDialogButtonClicked::IDCANCEL },
				{ "EDialogButtonClicked::IDABORT", (int64)EDialogButtonClicked::IDABORT },
				{ "EDialogButtonClicked::IDRETRY", (int64)EDialogButtonClicked::IDRETRY },
				{ "EDialogButtonClicked::IDIGNORE", (int64)EDialogButtonClicked::IDIGNORE },
				{ "EDialogButtonClicked::IDYES", (int64)EDialogButtonClicked::IDYES },
				{ "EDialogButtonClicked::IDNO", (int64)EDialogButtonClicked::IDNO },
				{ "EDialogButtonClicked::IDTRYAGAIN", (int64)EDialogButtonClicked::IDTRYAGAIN },
				{ "EDialogButtonClicked::IDCONTINUE", (int64)EDialogButtonClicked::IDCONTINUE },
			};
#if WITH_METADATA
			const UE4CodeGen_Private::FMetaDataPairParam Enum_MetaDataParams[] = {
				{ "BlueprintType", "true" },
				{ "IDABORT.DisplayName", "Abort" },
				{ "IDABORT.Name", "EDialogButtonClicked::IDABORT" },
				{ "IDCANCEL.DisplayName", "Cancel" },
				{ "IDCANCEL.Name", "EDialogButtonClicked::IDCANCEL" },
				{ "IDCONTINUE.DisplayName", "Continue" },
				{ "IDCONTINUE.Name", "EDialogButtonClicked::IDCONTINUE" },
				{ "IDIGNORE.DisplayName", "Ignore" },
				{ "IDIGNORE.Name", "EDialogButtonClicked::IDIGNORE" },
				{ "IDNO.DisplayName", "No" },
				{ "IDNO.Name", "EDialogButtonClicked::IDNO" },
				{ "IDNONE.DisplayName", "None" },
				{ "IDNONE.Name", "EDialogButtonClicked::IDNONE" },
				{ "IDOK.DisplayName", "OK" },
				{ "IDOK.Name", "EDialogButtonClicked::IDOK" },
				{ "IDRETRY.DisplayName", "Retry" },
				{ "IDRETRY.Name", "EDialogButtonClicked::IDRETRY" },
				{ "IDTRYAGAIN.DisplayName", "TryAgain" },
				{ "IDTRYAGAIN.Name", "EDialogButtonClicked::IDTRYAGAIN" },
				{ "IDYES.DisplayName", "Yes" },
				{ "IDYES.Name", "EDialogButtonClicked::IDYES" },
				{ "ModuleRelativePath", "Public/WindowsDialogBoxFunctionLibrary.h" },
			};
#endif
			static const UE4CodeGen_Private::FEnumParams EnumParams = {
				(UObject*(*)())Z_Construct_UPackage__Script_WindowsDialogBox,
				nullptr,
				"EDialogButtonClicked",
				"EDialogButtonClicked",
				Enumerators,
				UE_ARRAY_COUNT(Enumerators),
				RF_Public|RF_Transient|RF_MarkAsNative,
				EEnumFlags::None,
				UE4CodeGen_Private::EDynamicType::NotDynamic,
				(uint8)UEnum::ECppForm::EnumClass,
				METADATA_PARAMS(Enum_MetaDataParams, UE_ARRAY_COUNT(Enum_MetaDataParams))
			};
			UE4CodeGen_Private::ConstructUEnum(ReturnEnum, EnumParams);
		}
		return ReturnEnum;
	}
	static UEnum* EDialogIcon_StaticEnum()
	{
		static UEnum* Singleton = nullptr;
		if (!Singleton)
		{
			Singleton = GetStaticEnum(Z_Construct_UEnum_WindowsDialogBox_EDialogIcon, Z_Construct_UPackage__Script_WindowsDialogBox(), TEXT("EDialogIcon"));
		}
		return Singleton;
	}
	template<> WINDOWSDIALOGBOX_API UEnum* StaticEnum<EDialogIcon>()
	{
		return EDialogIcon_StaticEnum();
	}
	static FCompiledInDeferEnum Z_CompiledInDeferEnum_UEnum_EDialogIcon(EDialogIcon_StaticEnum, TEXT("/Script/WindowsDialogBox"), TEXT("EDialogIcon"), false, nullptr, nullptr);
	uint32 Get_Z_Construct_UEnum_WindowsDialogBox_EDialogIcon_Hash() { return 1995979645U; }
	UEnum* Z_Construct_UEnum_WindowsDialogBox_EDialogIcon()
	{
#if WITH_HOT_RELOAD
		UPackage* Outer = Z_Construct_UPackage__Script_WindowsDialogBox();
		static UEnum* ReturnEnum = FindExistingEnumIfHotReloadOrDynamic(Outer, TEXT("EDialogIcon"), 0, Get_Z_Construct_UEnum_WindowsDialogBox_EDialogIcon_Hash(), false);
#else
		static UEnum* ReturnEnum = nullptr;
#endif // WITH_HOT_RELOAD
		if (!ReturnEnum)
		{
			static const UE4CodeGen_Private::FEnumeratorParam Enumerators[] = {
				{ "EDialogIcon::MB_NONE", (int64)EDialogIcon::MB_NONE },
				{ "EDialogIcon::MB_ICONERROR", (int64)EDialogIcon::MB_ICONERROR },
				{ "EDialogIcon::MB_ICONWARNING", (int64)EDialogIcon::MB_ICONWARNING },
				{ "EDialogIcon::MB_ICONINFORMATION", (int64)EDialogIcon::MB_ICONINFORMATION },
			};
#if WITH_METADATA
			const UE4CodeGen_Private::FMetaDataPairParam Enum_MetaDataParams[] = {
				{ "BlueprintType", "true" },
				{ "MB_ICONERROR.DisplayName", "Stop-sign icon" },
				{ "MB_ICONERROR.Name", "EDialogIcon::MB_ICONERROR" },
				{ "MB_ICONINFORMATION.DisplayName", "Information-point icon" },
				{ "MB_ICONINFORMATION.Name", "EDialogIcon::MB_ICONINFORMATION" },
				{ "MB_ICONWARNING.DisplayName", "Exclamation-point icon" },
				{ "MB_ICONWARNING.Name", "EDialogIcon::MB_ICONWARNING" },
				{ "MB_NONE.DisplayName", "No icon" },
				{ "MB_NONE.Name", "EDialogIcon::MB_NONE" },
				{ "ModuleRelativePath", "Public/WindowsDialogBoxFunctionLibrary.h" },
			};
#endif
			static const UE4CodeGen_Private::FEnumParams EnumParams = {
				(UObject*(*)())Z_Construct_UPackage__Script_WindowsDialogBox,
				nullptr,
				"EDialogIcon",
				"EDialogIcon",
				Enumerators,
				UE_ARRAY_COUNT(Enumerators),
				RF_Public|RF_Transient|RF_MarkAsNative,
				EEnumFlags::None,
				UE4CodeGen_Private::EDynamicType::NotDynamic,
				(uint8)UEnum::ECppForm::EnumClass,
				METADATA_PARAMS(Enum_MetaDataParams, UE_ARRAY_COUNT(Enum_MetaDataParams))
			};
			UE4CodeGen_Private::ConstructUEnum(ReturnEnum, EnumParams);
		}
		return ReturnEnum;
	}
	static UEnum* EDialogButtons_StaticEnum()
	{
		static UEnum* Singleton = nullptr;
		if (!Singleton)
		{
			Singleton = GetStaticEnum(Z_Construct_UEnum_WindowsDialogBox_EDialogButtons, Z_Construct_UPackage__Script_WindowsDialogBox(), TEXT("EDialogButtons"));
		}
		return Singleton;
	}
	template<> WINDOWSDIALOGBOX_API UEnum* StaticEnum<EDialogButtons>()
	{
		return EDialogButtons_StaticEnum();
	}
	static FCompiledInDeferEnum Z_CompiledInDeferEnum_UEnum_EDialogButtons(EDialogButtons_StaticEnum, TEXT("/Script/WindowsDialogBox"), TEXT("EDialogButtons"), false, nullptr, nullptr);
	uint32 Get_Z_Construct_UEnum_WindowsDialogBox_EDialogButtons_Hash() { return 3770447578U; }
	UEnum* Z_Construct_UEnum_WindowsDialogBox_EDialogButtons()
	{
#if WITH_HOT_RELOAD
		UPackage* Outer = Z_Construct_UPackage__Script_WindowsDialogBox();
		static UEnum* ReturnEnum = FindExistingEnumIfHotReloadOrDynamic(Outer, TEXT("EDialogButtons"), 0, Get_Z_Construct_UEnum_WindowsDialogBox_EDialogButtons_Hash(), false);
#else
		static UEnum* ReturnEnum = nullptr;
#endif // WITH_HOT_RELOAD
		if (!ReturnEnum)
		{
			static const UE4CodeGen_Private::FEnumeratorParam Enumerators[] = {
				{ "EDialogButtons::MB_OK", (int64)EDialogButtons::MB_OK },
				{ "EDialogButtons::MB_OKCANCEL", (int64)EDialogButtons::MB_OKCANCEL },
				{ "EDialogButtons::MB_ABORTRETRYIGNORE", (int64)EDialogButtons::MB_ABORTRETRYIGNORE },
				{ "EDialogButtons::MB_YESNOCANCEL", (int64)EDialogButtons::MB_YESNOCANCEL },
				{ "EDialogButtons::MB_YESNO", (int64)EDialogButtons::MB_YESNO },
				{ "EDialogButtons::MB_RETRYCANCEL", (int64)EDialogButtons::MB_RETRYCANCEL },
				{ "EDialogButtons::MB_CANCELTRYCONTINUE", (int64)EDialogButtons::MB_CANCELTRYCONTINUE },
			};
#if WITH_METADATA
			const UE4CodeGen_Private::FMetaDataPairParam Enum_MetaDataParams[] = {
				{ "BlueprintType", "true" },
				{ "MB_ABORTRETRYIGNORE.DisplayName", "Abort, Retry, and Ignore" },
				{ "MB_ABORTRETRYIGNORE.Name", "EDialogButtons::MB_ABORTRETRYIGNORE" },
				{ "MB_CANCELTRYCONTINUE.DisplayName", "Cancel, Try Again, Continue" },
				{ "MB_CANCELTRYCONTINUE.Name", "EDialogButtons::MB_CANCELTRYCONTINUE" },
				{ "MB_OK.DisplayName", "OK" },
				{ "MB_OK.Name", "EDialogButtons::MB_OK" },
				{ "MB_OKCANCEL.DisplayName", "OK, Cancel" },
				{ "MB_OKCANCEL.Name", "EDialogButtons::MB_OKCANCEL" },
				{ "MB_RETRYCANCEL.DisplayName", "Retry, Cancel" },
				{ "MB_RETRYCANCEL.Name", "EDialogButtons::MB_RETRYCANCEL" },
				{ "MB_YESNO.DisplayName", "Yes, No" },
				{ "MB_YESNO.Name", "EDialogButtons::MB_YESNO" },
				{ "MB_YESNOCANCEL.DisplayName", "Yes, No, Cancel" },
				{ "MB_YESNOCANCEL.Name", "EDialogButtons::MB_YESNOCANCEL" },
				{ "ModuleRelativePath", "Public/WindowsDialogBoxFunctionLibrary.h" },
			};
#endif
			static const UE4CodeGen_Private::FEnumParams EnumParams = {
				(UObject*(*)())Z_Construct_UPackage__Script_WindowsDialogBox,
				nullptr,
				"EDialogButtons",
				"EDialogButtons",
				Enumerators,
				UE_ARRAY_COUNT(Enumerators),
				RF_Public|RF_Transient|RF_MarkAsNative,
				EEnumFlags::None,
				UE4CodeGen_Private::EDynamicType::NotDynamic,
				(uint8)UEnum::ECppForm::EnumClass,
				METADATA_PARAMS(Enum_MetaDataParams, UE_ARRAY_COUNT(Enum_MetaDataParams))
			};
			UE4CodeGen_Private::ConstructUEnum(ReturnEnum, EnumParams);
		}
		return ReturnEnum;
	}
	DEFINE_FUNCTION(UWindowsDialogBoxFunctionLibrary::execOpenDialog)
	{
		P_GET_PROPERTY(FStrProperty,Z_Param_DialogTitle);
		P_GET_PROPERTY(FStrProperty,Z_Param_DialogMessage);
		P_GET_ENUM(EDialogButtons,Z_Param_Buttons);
		P_GET_ENUM(EDialogIcon,Z_Param_Icon);
		P_FINISH;
		P_NATIVE_BEGIN;
		*(EDialogButtonClicked*)Z_Param__Result=UWindowsDialogBoxFunctionLibrary::OpenDialog(Z_Param_DialogTitle,Z_Param_DialogMessage,EDialogButtons(Z_Param_Buttons),EDialogIcon(Z_Param_Icon));
		P_NATIVE_END;
	}
	void UWindowsDialogBoxFunctionLibrary::StaticRegisterNativesUWindowsDialogBoxFunctionLibrary()
	{
		UClass* Class = UWindowsDialogBoxFunctionLibrary::StaticClass();
		static const FNameNativePtrPair Funcs[] = {
			{ "OpenDialog", &UWindowsDialogBoxFunctionLibrary::execOpenDialog },
		};
		FNativeFunctionRegistrar::RegisterFunctions(Class, Funcs, UE_ARRAY_COUNT(Funcs));
	}
	struct Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics
	{
		struct WindowsDialogBoxFunctionLibrary_eventOpenDialog_Parms
		{
			FString DialogTitle;
			FString DialogMessage;
			EDialogButtons Buttons;
			EDialogIcon Icon;
			EDialogButtonClicked ReturnValue;
		};
#if WITH_METADATA
		static const UE4CodeGen_Private::FMetaDataPairParam NewProp_DialogTitle_MetaData[];
#endif
		static const UE4CodeGen_Private::FStrPropertyParams NewProp_DialogTitle;
#if WITH_METADATA
		static const UE4CodeGen_Private::FMetaDataPairParam NewProp_DialogMessage_MetaData[];
#endif
		static const UE4CodeGen_Private::FStrPropertyParams NewProp_DialogMessage;
		static const UE4CodeGen_Private::FBytePropertyParams NewProp_Buttons_Underlying;
		static const UE4CodeGen_Private::FEnumPropertyParams NewProp_Buttons;
		static const UE4CodeGen_Private::FBytePropertyParams NewProp_Icon_Underlying;
		static const UE4CodeGen_Private::FEnumPropertyParams NewProp_Icon;
		static const UE4CodeGen_Private::FBytePropertyParams NewProp_ReturnValue_Underlying;
		static const UE4CodeGen_Private::FEnumPropertyParams NewProp_ReturnValue;
		static const UE4CodeGen_Private::FPropertyParamsBase* const PropPointers[];
#if WITH_METADATA
		static const UE4CodeGen_Private::FMetaDataPairParam Function_MetaDataParams[];
#endif
		static const UE4CodeGen_Private::FFunctionParams FuncParams;
	};
#if WITH_METADATA
	const UE4CodeGen_Private::FMetaDataPairParam Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_DialogTitle_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif
	const UE4CodeGen_Private::FStrPropertyParams Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_DialogTitle = { "DialogTitle", nullptr, (EPropertyFlags)0x0010000000000080, UE4CodeGen_Private::EPropertyGenFlags::Str, RF_Public|RF_Transient|RF_MarkAsNative, 1, STRUCT_OFFSET(WindowsDialogBoxFunctionLibrary_eventOpenDialog_Parms, DialogTitle), METADATA_PARAMS(Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_DialogTitle_MetaData, UE_ARRAY_COUNT(Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_DialogTitle_MetaData)) };
#if WITH_METADATA
	const UE4CodeGen_Private::FMetaDataPairParam Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_DialogMessage_MetaData[] = {
		{ "NativeConst", "" },
	};
#endif
	const UE4CodeGen_Private::FStrPropertyParams Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_DialogMessage = { "DialogMessage", nullptr, (EPropertyFlags)0x0010000000000080, UE4CodeGen_Private::EPropertyGenFlags::Str, RF_Public|RF_Transient|RF_MarkAsNative, 1, STRUCT_OFFSET(WindowsDialogBoxFunctionLibrary_eventOpenDialog_Parms, DialogMessage), METADATA_PARAMS(Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_DialogMessage_MetaData, UE_ARRAY_COUNT(Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_DialogMessage_MetaData)) };
	const UE4CodeGen_Private::FBytePropertyParams Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_Buttons_Underlying = { "UnderlyingType", nullptr, (EPropertyFlags)0x0000000000000000, UE4CodeGen_Private::EPropertyGenFlags::Byte, RF_Public|RF_Transient|RF_MarkAsNative, 1, 0, nullptr, METADATA_PARAMS(nullptr, 0) };
	const UE4CodeGen_Private::FEnumPropertyParams Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_Buttons = { "Buttons", nullptr, (EPropertyFlags)0x0010000000000080, UE4CodeGen_Private::EPropertyGenFlags::Enum, RF_Public|RF_Transient|RF_MarkAsNative, 1, STRUCT_OFFSET(WindowsDialogBoxFunctionLibrary_eventOpenDialog_Parms, Buttons), Z_Construct_UEnum_WindowsDialogBox_EDialogButtons, METADATA_PARAMS(nullptr, 0) };
	const UE4CodeGen_Private::FBytePropertyParams Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_Icon_Underlying = { "UnderlyingType", nullptr, (EPropertyFlags)0x0000000000000000, UE4CodeGen_Private::EPropertyGenFlags::Byte, RF_Public|RF_Transient|RF_MarkAsNative, 1, 0, nullptr, METADATA_PARAMS(nullptr, 0) };
	const UE4CodeGen_Private::FEnumPropertyParams Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_Icon = { "Icon", nullptr, (EPropertyFlags)0x0010000000000080, UE4CodeGen_Private::EPropertyGenFlags::Enum, RF_Public|RF_Transient|RF_MarkAsNative, 1, STRUCT_OFFSET(WindowsDialogBoxFunctionLibrary_eventOpenDialog_Parms, Icon), Z_Construct_UEnum_WindowsDialogBox_EDialogIcon, METADATA_PARAMS(nullptr, 0) };
	const UE4CodeGen_Private::FBytePropertyParams Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_ReturnValue_Underlying = { "UnderlyingType", nullptr, (EPropertyFlags)0x0000000000000000, UE4CodeGen_Private::EPropertyGenFlags::Byte, RF_Public|RF_Transient|RF_MarkAsNative, 1, 0, nullptr, METADATA_PARAMS(nullptr, 0) };
	const UE4CodeGen_Private::FEnumPropertyParams Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UE4CodeGen_Private::EPropertyGenFlags::Enum, RF_Public|RF_Transient|RF_MarkAsNative, 1, STRUCT_OFFSET(WindowsDialogBoxFunctionLibrary_eventOpenDialog_Parms, ReturnValue), Z_Construct_UEnum_WindowsDialogBox_EDialogButtonClicked, METADATA_PARAMS(nullptr, 0) };
	const UE4CodeGen_Private::FPropertyParamsBase* const Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::PropPointers[] = {
		(const UE4CodeGen_Private::FPropertyParamsBase*)&Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_DialogTitle,
		(const UE4CodeGen_Private::FPropertyParamsBase*)&Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_DialogMessage,
		(const UE4CodeGen_Private::FPropertyParamsBase*)&Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_Buttons_Underlying,
		(const UE4CodeGen_Private::FPropertyParamsBase*)&Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_Buttons,
		(const UE4CodeGen_Private::FPropertyParamsBase*)&Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_Icon_Underlying,
		(const UE4CodeGen_Private::FPropertyParamsBase*)&Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_Icon,
		(const UE4CodeGen_Private::FPropertyParamsBase*)&Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_ReturnValue_Underlying,
		(const UE4CodeGen_Private::FPropertyParamsBase*)&Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::NewProp_ReturnValue,
	};
#if WITH_METADATA
	const UE4CodeGen_Private::FMetaDataPairParam Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::Function_MetaDataParams[] = {
		{ "Category", "WindowsDialogBox" },
		{ "ModuleRelativePath", "Public/WindowsDialogBoxFunctionLibrary.h" },
	};
#endif
	const UE4CodeGen_Private::FFunctionParams Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::FuncParams = { (UObject*(*)())Z_Construct_UClass_UWindowsDialogBoxFunctionLibrary, nullptr, "OpenDialog", nullptr, nullptr, sizeof(WindowsDialogBoxFunctionLibrary_eventOpenDialog_Parms), Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::PropPointers, UE_ARRAY_COUNT(Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::PropPointers), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04042401, 0, 0, METADATA_PARAMS(Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::Function_MetaDataParams, UE_ARRAY_COUNT(Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::Function_MetaDataParams)) };
	UFunction* Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog()
	{
		static UFunction* ReturnFunction = nullptr;
		if (!ReturnFunction)
		{
			UE4CodeGen_Private::ConstructUFunction(ReturnFunction, Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog_Statics::FuncParams);
		}
		return ReturnFunction;
	}
	UClass* Z_Construct_UClass_UWindowsDialogBoxFunctionLibrary_NoRegister()
	{
		return UWindowsDialogBoxFunctionLibrary::StaticClass();
	}
	struct Z_Construct_UClass_UWindowsDialogBoxFunctionLibrary_Statics
	{
		static UObject* (*const DependentSingletons[])();
		static const FClassFunctionLinkInfo FuncInfo[];
#if WITH_METADATA
		static const UE4CodeGen_Private::FMetaDataPairParam Class_MetaDataParams[];
#endif
		static const FCppClassTypeInfoStatic StaticCppClassTypeInfo;
		static const UE4CodeGen_Private::FClassParams ClassParams;
	};
	UObject* (*const Z_Construct_UClass_UWindowsDialogBoxFunctionLibrary_Statics::DependentSingletons[])() = {
		(UObject* (*)())Z_Construct_UClass_UBlueprintFunctionLibrary,
		(UObject* (*)())Z_Construct_UPackage__Script_WindowsDialogBox,
	};
	const FClassFunctionLinkInfo Z_Construct_UClass_UWindowsDialogBoxFunctionLibrary_Statics::FuncInfo[] = {
		{ &Z_Construct_UFunction_UWindowsDialogBoxFunctionLibrary_OpenDialog, "OpenDialog" }, // 3992602569
	};
#if WITH_METADATA
	const UE4CodeGen_Private::FMetaDataPairParam Z_Construct_UClass_UWindowsDialogBoxFunctionLibrary_Statics::Class_MetaDataParams[] = {
		{ "Comment", "/**\n * \n */" },
		{ "IncludePath", "WindowsDialogBoxFunctionLibrary.h" },
		{ "ModuleRelativePath", "Public/WindowsDialogBoxFunctionLibrary.h" },
	};
#endif
	const FCppClassTypeInfoStatic Z_Construct_UClass_UWindowsDialogBoxFunctionLibrary_Statics::StaticCppClassTypeInfo = {
		TCppClassTypeTraits<UWindowsDialogBoxFunctionLibrary>::IsAbstract,
	};
	const UE4CodeGen_Private::FClassParams Z_Construct_UClass_UWindowsDialogBoxFunctionLibrary_Statics::ClassParams = {
		&UWindowsDialogBoxFunctionLibrary::StaticClass,
		nullptr,
		&StaticCppClassTypeInfo,
		DependentSingletons,
		FuncInfo,
		nullptr,
		nullptr,
		UE_ARRAY_COUNT(DependentSingletons),
		UE_ARRAY_COUNT(FuncInfo),
		0,
		0,
		0x001000A0u,
		METADATA_PARAMS(Z_Construct_UClass_UWindowsDialogBoxFunctionLibrary_Statics::Class_MetaDataParams, UE_ARRAY_COUNT(Z_Construct_UClass_UWindowsDialogBoxFunctionLibrary_Statics::Class_MetaDataParams))
	};
	UClass* Z_Construct_UClass_UWindowsDialogBoxFunctionLibrary()
	{
		static UClass* OuterClass = nullptr;
		if (!OuterClass)
		{
			UE4CodeGen_Private::ConstructUClass(OuterClass, Z_Construct_UClass_UWindowsDialogBoxFunctionLibrary_Statics::ClassParams);
		}
		return OuterClass;
	}
	IMPLEMENT_CLASS(UWindowsDialogBoxFunctionLibrary, 749259856);
	template<> WINDOWSDIALOGBOX_API UClass* StaticClass<UWindowsDialogBoxFunctionLibrary>()
	{
		return UWindowsDialogBoxFunctionLibrary::StaticClass();
	}
	static FCompiledInDefer Z_CompiledInDefer_UClass_UWindowsDialogBoxFunctionLibrary(Z_Construct_UClass_UWindowsDialogBoxFunctionLibrary, &UWindowsDialogBoxFunctionLibrary::StaticClass, TEXT("/Script/WindowsDialogBox"), TEXT("UWindowsDialogBoxFunctionLibrary"), false, nullptr, nullptr, nullptr);
	DEFINE_VTABLE_PTR_HELPER_CTOR(UWindowsDialogBoxFunctionLibrary);
PRAGMA_ENABLE_DEPRECATION_WARNINGS
#ifdef _MSC_VER
#pragma warning (pop)
#endif
