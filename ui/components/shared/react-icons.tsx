import type { ReactElement } from "react";
import { BiEdit } from "react-icons/bi";
import { CiCalendar } from "react-icons/ci";
import { FaBriefcase, FaBusinessTime, FaLaptopCode, FaMoneyBillWave, FaPaintBrush, FaPlaneDeparture, FaRegHeart, FaRegSmile, FaUserTie } from "react-icons/fa";
import { FiRefreshCcw, FiTrash2 } from "react-icons/fi";
import { GoPackage, GoPlus } from "react-icons/go";
import { HiHome, HiMiniRectangleStack } from "react-icons/hi2";
import { PiSwatches } from "react-icons/pi";
import { RiApps2AddFill } from "react-icons/ri";
import type { IconBaseProps, IconType } from "react-icons/lib";

type TypedIcon = (props: IconBaseProps) => ReactElement | null;

function typedIcon(Icon: IconType): TypedIcon {
  return function ReactIcon(props: IconBaseProps): ReactElement | null {
    const node = Icon(props);
    return node == null || typeof node === "boolean" ? null : <>{node}</>;
  };
}

export const BiEditIcon = typedIcon(BiEdit);
export const CiCalendarIcon = typedIcon(CiCalendar);
export const FaBriefcaseIcon = typedIcon(FaBriefcase);
export const FaBusinessTimeIcon = typedIcon(FaBusinessTime);
export const FaLaptopCodeIcon = typedIcon(FaLaptopCode);
export const FaMoneyBillWaveIcon = typedIcon(FaMoneyBillWave);
export const FaPaintBrushIcon = typedIcon(FaPaintBrush);
export const FaPlaneDepartureIcon = typedIcon(FaPlaneDeparture);
export const FaRegHeartIcon = typedIcon(FaRegHeart);
export const FaRegSmileIcon = typedIcon(FaRegSmile);
export const FaUserTieIcon = typedIcon(FaUserTie);
export const FiRefreshCcwIcon = typedIcon(FiRefreshCcw);
export const FiTrash2Icon = typedIcon(FiTrash2);
export const GoPackageIcon = typedIcon(GoPackage);
export const GoPlusIcon = typedIcon(GoPlus);
export const HiHomeIcon = typedIcon(HiHome);
export const HiMiniRectangleStackIcon = typedIcon(HiMiniRectangleStack);
export const PiSwatchesIcon = typedIcon(PiSwatches);
export const RiApps2AddFillIcon = typedIcon(RiApps2AddFill);
