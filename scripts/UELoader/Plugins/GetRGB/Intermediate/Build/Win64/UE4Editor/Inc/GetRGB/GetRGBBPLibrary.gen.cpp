// Copyright Epic Games, Inc. All Rights Reserved.
/*===========================================================================
	Generated code exported from UnrealHeaderTool.
	DO NOT modify this manually! Edit the corresponding .h files instead!
===========================================================================*/

#include "UObject/GeneratedCppIncludes.h"
#include "GetRGB/Public/GetRGBBPLibrary.h"
#ifdef _MSC_VER
#pragma warning (push)
#pragma warning (disable : 4883)
#endif
PRAGMA_DISABLE_DEPRECATION_WARNINGS
void EmptyLinkFunctionForGeneratedCodeGetRGBBPLibrary() {}
// Cross Module References
	GETRGB_API UClass* Z_Construct_UClass_UGetRGBBPLibrary_NoRegister();
	GETRGB_API UClass* Z_Construct_UClass_UGetRGBBPLibrary();
	ENGINE_API UClass* Z_Construct_UClass_UBlueprintFunctionLibrary();
	UPackage* Z_Construct_UPackage__Script_GetRGB();
	COREUOBJECT_API UScriptStruct* Z_Construct_UScriptStruct_FColor();
	ENGINE_API UClass* Z_Construct_UClass_UTexture2D_NoRegister();
// End Cross Module References
	DEFINE_FUNCTION(UGetRGBBPLibrary::execGetPictureRGBPixel)
	{
		P_GET_OBJECT(UTexture2D,Z_Param_RGBTexture);
		P_FINISH;
		P_NATIVE_BEGIN;
		*(TArray<FColor>*)Z_Param__Result=UGetRGBBPLibrary::GetPictureRGBPixel(Z_Param_RGBTexture);
		P_NATIVE_END;
	}
	DEFINE_FUNCTION(UGetRGBBPLibrary::execGetRGBSampleFunction)
	{
		P_GET_PROPERTY(FFloatProperty,Z_Param_Param);
		P_FINISH;
		P_NATIVE_BEGIN;
		*(float*)Z_Param__Result=UGetRGBBPLibrary::GetRGBSampleFunction(Z_Param_Param);
		P_NATIVE_END;
	}
	void UGetRGBBPLibrary::StaticRegisterNativesUGetRGBBPLibrary()
	{
		UClass* Class = UGetRGBBPLibrary::StaticClass();
		static const FNameNativePtrPair Funcs[] = {
			{ "GetPictureRGBPixel", &UGetRGBBPLibrary::execGetPictureRGBPixel },
			{ "GetRGBSampleFunction", &UGetRGBBPLibrary::execGetRGBSampleFunction },
		};
		FNativeFunctionRegistrar::RegisterFunctions(Class, Funcs, UE_ARRAY_COUNT(Funcs));
	}
	struct Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel_Statics
	{
		struct GetRGBBPLibrary_eventGetPictureRGBPixel_Parms
		{
			UTexture2D* RGBTexture;
			TArray<FColor> ReturnValue;
		};
		static const UE4CodeGen_Private::FArrayPropertyParams NewProp_ReturnValue;
		static const UE4CodeGen_Private::FStructPropertyParams NewProp_ReturnValue_Inner;
		static const UE4CodeGen_Private::FObjectPropertyParams NewProp_RGBTexture;
		static const UE4CodeGen_Private::FPropertyParamsBase* const PropPointers[];
#if WITH_METADATA
		static const UE4CodeGen_Private::FMetaDataPairParam Function_MetaDataParams[];
#endif
		static const UE4CodeGen_Private::FFunctionParams FuncParams;
	};
	const UE4CodeGen_Private::FArrayPropertyParams Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel_Statics::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UE4CodeGen_Private::EPropertyGenFlags::Array, RF_Public|RF_Transient|RF_MarkAsNative, 1, STRUCT_OFFSET(GetRGBBPLibrary_eventGetPictureRGBPixel_Parms, ReturnValue), EArrayPropertyFlags::None, METADATA_PARAMS(nullptr, 0) };
	const UE4CodeGen_Private::FStructPropertyParams Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel_Statics::NewProp_ReturnValue_Inner = { "ReturnValue", nullptr, (EPropertyFlags)0x0000000000000000, UE4CodeGen_Private::EPropertyGenFlags::Struct, RF_Public|RF_Transient|RF_MarkAsNative, 1, 0, Z_Construct_UScriptStruct_FColor, METADATA_PARAMS(nullptr, 0) };
	const UE4CodeGen_Private::FObjectPropertyParams Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel_Statics::NewProp_RGBTexture = { "RGBTexture", nullptr, (EPropertyFlags)0x0010000000000080, UE4CodeGen_Private::EPropertyGenFlags::Object, RF_Public|RF_Transient|RF_MarkAsNative, 1, STRUCT_OFFSET(GetRGBBPLibrary_eventGetPictureRGBPixel_Parms, RGBTexture), Z_Construct_UClass_UTexture2D_NoRegister, METADATA_PARAMS(nullptr, 0) };
	const UE4CodeGen_Private::FPropertyParamsBase* const Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel_Statics::PropPointers[] = {
		(const UE4CodeGen_Private::FPropertyParamsBase*)&Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel_Statics::NewProp_ReturnValue,
		(const UE4CodeGen_Private::FPropertyParamsBase*)&Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel_Statics::NewProp_ReturnValue_Inner,
		(const UE4CodeGen_Private::FPropertyParamsBase*)&Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel_Statics::NewProp_RGBTexture,
	};
#if WITH_METADATA
	const UE4CodeGen_Private::FMetaDataPairParam Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel_Statics::Function_MetaDataParams[] = {
		{ "Category", "GetPicPixel" },
		{ "ModuleRelativePath", "Public/GetRGBBPLibrary.h" },
	};
#endif
	const UE4CodeGen_Private::FFunctionParams Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel_Statics::FuncParams = { (UObject*(*)())Z_Construct_UClass_UGetRGBBPLibrary, nullptr, "GetPictureRGBPixel", nullptr, nullptr, sizeof(GetRGBBPLibrary_eventGetPictureRGBPixel_Parms), Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel_Statics::PropPointers, UE_ARRAY_COUNT(Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel_Statics::PropPointers), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel_Statics::Function_MetaDataParams, UE_ARRAY_COUNT(Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel_Statics::Function_MetaDataParams)) };
	UFunction* Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel()
	{
		static UFunction* ReturnFunction = nullptr;
		if (!ReturnFunction)
		{
			UE4CodeGen_Private::ConstructUFunction(ReturnFunction, Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel_Statics::FuncParams);
		}
		return ReturnFunction;
	}
	struct Z_Construct_UFunction_UGetRGBBPLibrary_GetRGBSampleFunction_Statics
	{
		struct GetRGBBPLibrary_eventGetRGBSampleFunction_Parms
		{
			float Param;
			float ReturnValue;
		};
		static const UE4CodeGen_Private::FFloatPropertyParams NewProp_ReturnValue;
		static const UE4CodeGen_Private::FFloatPropertyParams NewProp_Param;
		static const UE4CodeGen_Private::FPropertyParamsBase* const PropPointers[];
#if WITH_METADATA
		static const UE4CodeGen_Private::FMetaDataPairParam Function_MetaDataParams[];
#endif
		static const UE4CodeGen_Private::FFunctionParams FuncParams;
	};
	const UE4CodeGen_Private::FFloatPropertyParams Z_Construct_UFunction_UGetRGBBPLibrary_GetRGBSampleFunction_Statics::NewProp_ReturnValue = { "ReturnValue", nullptr, (EPropertyFlags)0x0010000000000580, UE4CodeGen_Private::EPropertyGenFlags::Float, RF_Public|RF_Transient|RF_MarkAsNative, 1, STRUCT_OFFSET(GetRGBBPLibrary_eventGetRGBSampleFunction_Parms, ReturnValue), METADATA_PARAMS(nullptr, 0) };
	const UE4CodeGen_Private::FFloatPropertyParams Z_Construct_UFunction_UGetRGBBPLibrary_GetRGBSampleFunction_Statics::NewProp_Param = { "Param", nullptr, (EPropertyFlags)0x0010000000000080, UE4CodeGen_Private::EPropertyGenFlags::Float, RF_Public|RF_Transient|RF_MarkAsNative, 1, STRUCT_OFFSET(GetRGBBPLibrary_eventGetRGBSampleFunction_Parms, Param), METADATA_PARAMS(nullptr, 0) };
	const UE4CodeGen_Private::FPropertyParamsBase* const Z_Construct_UFunction_UGetRGBBPLibrary_GetRGBSampleFunction_Statics::PropPointers[] = {
		(const UE4CodeGen_Private::FPropertyParamsBase*)&Z_Construct_UFunction_UGetRGBBPLibrary_GetRGBSampleFunction_Statics::NewProp_ReturnValue,
		(const UE4CodeGen_Private::FPropertyParamsBase*)&Z_Construct_UFunction_UGetRGBBPLibrary_GetRGBSampleFunction_Statics::NewProp_Param,
	};
#if WITH_METADATA
	const UE4CodeGen_Private::FMetaDataPairParam Z_Construct_UFunction_UGetRGBBPLibrary_GetRGBSampleFunction_Statics::Function_MetaDataParams[] = {
		{ "Category", "GetRGBTesting" },
		{ "DisplayName", "Execute Sample function" },
		{ "Keywords", "GetRGB sample test testing" },
		{ "ModuleRelativePath", "Public/GetRGBBPLibrary.h" },
	};
#endif
	const UE4CodeGen_Private::FFunctionParams Z_Construct_UFunction_UGetRGBBPLibrary_GetRGBSampleFunction_Statics::FuncParams = { (UObject*(*)())Z_Construct_UClass_UGetRGBBPLibrary, nullptr, "GetRGBSampleFunction", nullptr, nullptr, sizeof(GetRGBBPLibrary_eventGetRGBSampleFunction_Parms), Z_Construct_UFunction_UGetRGBBPLibrary_GetRGBSampleFunction_Statics::PropPointers, UE_ARRAY_COUNT(Z_Construct_UFunction_UGetRGBBPLibrary_GetRGBSampleFunction_Statics::PropPointers), RF_Public|RF_Transient|RF_MarkAsNative, (EFunctionFlags)0x04022401, 0, 0, METADATA_PARAMS(Z_Construct_UFunction_UGetRGBBPLibrary_GetRGBSampleFunction_Statics::Function_MetaDataParams, UE_ARRAY_COUNT(Z_Construct_UFunction_UGetRGBBPLibrary_GetRGBSampleFunction_Statics::Function_MetaDataParams)) };
	UFunction* Z_Construct_UFunction_UGetRGBBPLibrary_GetRGBSampleFunction()
	{
		static UFunction* ReturnFunction = nullptr;
		if (!ReturnFunction)
		{
			UE4CodeGen_Private::ConstructUFunction(ReturnFunction, Z_Construct_UFunction_UGetRGBBPLibrary_GetRGBSampleFunction_Statics::FuncParams);
		}
		return ReturnFunction;
	}
	UClass* Z_Construct_UClass_UGetRGBBPLibrary_NoRegister()
	{
		return UGetRGBBPLibrary::StaticClass();
	}
	struct Z_Construct_UClass_UGetRGBBPLibrary_Statics
	{
		static UObject* (*const DependentSingletons[])();
		static const FClassFunctionLinkInfo FuncInfo[];
#if WITH_METADATA
		static const UE4CodeGen_Private::FMetaDataPairParam Class_MetaDataParams[];
#endif
		static const FCppClassTypeInfoStatic StaticCppClassTypeInfo;
		static const UE4CodeGen_Private::FClassParams ClassParams;
	};
	UObject* (*const Z_Construct_UClass_UGetRGBBPLibrary_Statics::DependentSingletons[])() = {
		(UObject* (*)())Z_Construct_UClass_UBlueprintFunctionLibrary,
		(UObject* (*)())Z_Construct_UPackage__Script_GetRGB,
	};
	const FClassFunctionLinkInfo Z_Construct_UClass_UGetRGBBPLibrary_Statics::FuncInfo[] = {
		{ &Z_Construct_UFunction_UGetRGBBPLibrary_GetPictureRGBPixel, "GetPictureRGBPixel" }, // 3658743994
		{ &Z_Construct_UFunction_UGetRGBBPLibrary_GetRGBSampleFunction, "GetRGBSampleFunction" }, // 2361568033
	};
#if WITH_METADATA
	const UE4CodeGen_Private::FMetaDataPairParam Z_Construct_UClass_UGetRGBBPLibrary_Statics::Class_MetaDataParams[] = {
		{ "Comment", "/* \n*\x09""Function library class.\n*\x09""Each function in it is expected to be static and represents blueprint node that can be called in any blueprint.\n*\n*\x09When declaring function you can define metadata for the node. Key function specifiers will be BlueprintPure and BlueprintCallable.\n*\x09""BlueprintPure - means the function does not affect the owning object in any way and thus creates a node without Exec pins.\n*\x09""BlueprintCallable - makes a function which can be executed in Blueprints - Thus it has Exec pins.\n*\x09""DisplayName - full name of the node, shown when you mouse over the node and in the blueprint drop down menu.\n*\x09\x09\x09\x09Its lets you name the node using characters not allowed in C++ function names.\n*\x09""CompactNodeTitle - the word(s) that appear on the node.\n*\x09Keywords -\x09the list of keywords that helps you to find node when you search for it using Blueprint drop-down menu. \n*\x09\x09\x09\x09Good example is \"Print String\" node which you can find also by using keyword \"log\".\n*\x09""Category -\x09the category your node will be under in the Blueprint drop-down menu.\n*\n*\x09""For more info on custom blueprint nodes visit documentation:\n*\x09https://wiki.unrealengine.com/Custom_Blueprint_Node_Creation\n*/" },
		{ "IncludePath", "GetRGBBPLibrary.h" },
		{ "ModuleRelativePath", "Public/GetRGBBPLibrary.h" },
		{ "ToolTip", "*      Function library class.\n*      Each function in it is expected to be static and represents blueprint node that can be called in any blueprint.\n*\n*      When declaring function you can define metadata for the node. Key function specifiers will be BlueprintPure and BlueprintCallable.\n*      BlueprintPure - means the function does not affect the owning object in any way and thus creates a node without Exec pins.\n*      BlueprintCallable - makes a function which can be executed in Blueprints - Thus it has Exec pins.\n*      DisplayName - full name of the node, shown when you mouse over the node and in the blueprint drop down menu.\n*                              Its lets you name the node using characters not allowed in C++ function names.\n*      CompactNodeTitle - the word(s) that appear on the node.\n*      Keywords -      the list of keywords that helps you to find node when you search for it using Blueprint drop-down menu.\n*                              Good example is \"Print String\" node which you can find also by using keyword \"log\".\n*      Category -      the category your node will be under in the Blueprint drop-down menu.\n*\n*      For more info on custom blueprint nodes visit documentation:\n*      https://wiki.unrealengine.com/Custom_Blueprint_Node_Creation" },
	};
#endif
	const FCppClassTypeInfoStatic Z_Construct_UClass_UGetRGBBPLibrary_Statics::StaticCppClassTypeInfo = {
		TCppClassTypeTraits<UGetRGBBPLibrary>::IsAbstract,
	};
	const UE4CodeGen_Private::FClassParams Z_Construct_UClass_UGetRGBBPLibrary_Statics::ClassParams = {
		&UGetRGBBPLibrary::StaticClass,
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
		0x000000A0u,
		METADATA_PARAMS(Z_Construct_UClass_UGetRGBBPLibrary_Statics::Class_MetaDataParams, UE_ARRAY_COUNT(Z_Construct_UClass_UGetRGBBPLibrary_Statics::Class_MetaDataParams))
	};
	UClass* Z_Construct_UClass_UGetRGBBPLibrary()
	{
		static UClass* OuterClass = nullptr;
		if (!OuterClass)
		{
			UE4CodeGen_Private::ConstructUClass(OuterClass, Z_Construct_UClass_UGetRGBBPLibrary_Statics::ClassParams);
		}
		return OuterClass;
	}
	IMPLEMENT_CLASS(UGetRGBBPLibrary, 4102427313);
	template<> GETRGB_API UClass* StaticClass<UGetRGBBPLibrary>()
	{
		return UGetRGBBPLibrary::StaticClass();
	}
	static FCompiledInDefer Z_CompiledInDefer_UClass_UGetRGBBPLibrary(Z_Construct_UClass_UGetRGBBPLibrary, &UGetRGBBPLibrary::StaticClass, TEXT("/Script/GetRGB"), TEXT("UGetRGBBPLibrary"), false, nullptr, nullptr, nullptr);
	DEFINE_VTABLE_PTR_HELPER_CTOR(UGetRGBBPLibrary);
PRAGMA_ENABLE_DEPRECATION_WARNINGS
#ifdef _MSC_VER
#pragma warning (pop)
#endif
