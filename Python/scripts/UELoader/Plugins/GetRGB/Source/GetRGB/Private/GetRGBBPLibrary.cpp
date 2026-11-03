// Copyright Epic Games, Inc. All Rights Reserved.

#include "GetRGBBPLibrary.h"
#include "GetRGB.h"

UGetRGBBPLibrary::UGetRGBBPLibrary(const FObjectInitializer& ObjectInitializer)
: Super(ObjectInitializer)
{

}

float UGetRGBBPLibrary::GetRGBSampleFunction(float Param)
{
	return -1;
}

TArray<FColor> UGetRGBBPLibrary::GetPictureRGBPixel(UTexture2D *RGBTexture)
{
	TArray64<uint8>PicData;//存放每个点的灰度值
	TArray<FColor>PixelColorArray;//存放每个点的颜色值

	RGBTexture->Source.GetMipData(PicData, 0);//读取图片的像素R、B、G、A值依次排列
	//auto Format = MyTexture->Source.GetFormat();
	FColor* Colors = (FColor*)PicData.GetData();//每四个整数（RGBA）组成一个颜色数组

	int XLength = RGBTexture->Source.GetSizeX();
	int YLength = RGBTexture->Source.GetSizeY();

	for (int y = 0; y < YLength; y++)
	{
		for (int x = 0; x < XLength; x++)
		{
			FColor PixelColor = Colors[y * XLength + x];
			PixelColorArray.Add(PixelColor);
		}
	}
	return PixelColorArray;
}