// Copyright Epic Games, Inc. All Rights Reserved.
/*===========================================================================
	Generated code exported from UnrealHeaderTool.
	DO NOT modify this manually! Edit the corresponding .h files instead!
===========================================================================*/

#include "UObject/ObjectMacros.h"
#include "UObject/ScriptMacros.h"

PRAGMA_DISABLE_DEPRECATION_WARNINGS
class UTexture2D;
struct FColor;
#ifdef GETRGB_GetRGBBPLibrary_generated_h
#error "GetRGBBPLibrary.generated.h already included, missing '#pragma once' in GetRGBBPLibrary.h"
#endif
#define GETRGB_GetRGBBPLibrary_generated_h

#define RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_SPARSE_DATA
#define RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_RPC_WRAPPERS \
 \
	DECLARE_FUNCTION(execGetPictureRGBPixel); \
	DECLARE_FUNCTION(execGetRGBSampleFunction);


#define RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_RPC_WRAPPERS_NO_PURE_DECLS \
 \
	DECLARE_FUNCTION(execGetPictureRGBPixel); \
	DECLARE_FUNCTION(execGetRGBSampleFunction);


#define RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_INCLASS_NO_PURE_DECLS \
private: \
	static void StaticRegisterNativesUGetRGBBPLibrary(); \
	friend struct Z_Construct_UClass_UGetRGBBPLibrary_Statics; \
public: \
	DECLARE_CLASS(UGetRGBBPLibrary, UBlueprintFunctionLibrary, COMPILED_IN_FLAGS(0), CASTCLASS_None, TEXT("/Script/GetRGB"), NO_API) \
	DECLARE_SERIALIZER(UGetRGBBPLibrary)


#define RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_INCLASS \
private: \
	static void StaticRegisterNativesUGetRGBBPLibrary(); \
	friend struct Z_Construct_UClass_UGetRGBBPLibrary_Statics; \
public: \
	DECLARE_CLASS(UGetRGBBPLibrary, UBlueprintFunctionLibrary, COMPILED_IN_FLAGS(0), CASTCLASS_None, TEXT("/Script/GetRGB"), NO_API) \
	DECLARE_SERIALIZER(UGetRGBBPLibrary)


#define RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_STANDARD_CONSTRUCTORS \
	/** Standard constructor, called after all reflected properties have been initialized */ \
	NO_API UGetRGBBPLibrary(const FObjectInitializer& ObjectInitializer = FObjectInitializer::Get()); \
	DEFINE_DEFAULT_OBJECT_INITIALIZER_CONSTRUCTOR_CALL(UGetRGBBPLibrary) \
	DECLARE_VTABLE_PTR_HELPER_CTOR(NO_API, UGetRGBBPLibrary); \
DEFINE_VTABLE_PTR_HELPER_CTOR_CALLER(UGetRGBBPLibrary); \
private: \
	/** Private move- and copy-constructors, should never be used */ \
	NO_API UGetRGBBPLibrary(UGetRGBBPLibrary&&); \
	NO_API UGetRGBBPLibrary(const UGetRGBBPLibrary&); \
public:


#define RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_ENHANCED_CONSTRUCTORS \
	/** Standard constructor, called after all reflected properties have been initialized */ \
	NO_API UGetRGBBPLibrary(const FObjectInitializer& ObjectInitializer = FObjectInitializer::Get()) : Super(ObjectInitializer) { }; \
private: \
	/** Private move- and copy-constructors, should never be used */ \
	NO_API UGetRGBBPLibrary(UGetRGBBPLibrary&&); \
	NO_API UGetRGBBPLibrary(const UGetRGBBPLibrary&); \
public: \
	DECLARE_VTABLE_PTR_HELPER_CTOR(NO_API, UGetRGBBPLibrary); \
DEFINE_VTABLE_PTR_HELPER_CTOR_CALLER(UGetRGBBPLibrary); \
	DEFINE_DEFAULT_OBJECT_INITIALIZER_CONSTRUCTOR_CALL(UGetRGBBPLibrary)


#define RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_PRIVATE_PROPERTY_OFFSET
#define RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_25_PROLOG
#define RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_GENERATED_BODY_LEGACY \
PRAGMA_DISABLE_DEPRECATION_WARNINGS \
public: \
	RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_PRIVATE_PROPERTY_OFFSET \
	RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_SPARSE_DATA \
	RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_RPC_WRAPPERS \
	RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_INCLASS \
	RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_STANDARD_CONSTRUCTORS \
public: \
PRAGMA_ENABLE_DEPRECATION_WARNINGS


#define RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_GENERATED_BODY \
PRAGMA_DISABLE_DEPRECATION_WARNINGS \
public: \
	RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_PRIVATE_PROPERTY_OFFSET \
	RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_SPARSE_DATA \
	RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_RPC_WRAPPERS_NO_PURE_DECLS \
	RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_INCLASS_NO_PURE_DECLS \
	RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h_28_ENHANCED_CONSTRUCTORS \
static_assert(false, "Unknown access specifier for GENERATED_BODY() macro in class GetRGBBPLibrary."); \
PRAGMA_ENABLE_DEPRECATION_WARNINGS


template<> GETRGB_API UClass* StaticClass<class UGetRGBBPLibrary>();

#undef CURRENT_FILE_ID
#define CURRENT_FILE_ID RGBTest_Plugins_GetRGB_Source_GetRGB_Public_GetRGBBPLibrary_h


PRAGMA_ENABLE_DEPRECATION_WARNINGS
