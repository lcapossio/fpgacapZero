/* SPDX-License-Identifier: Apache-2.0
 * Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
 *
 * Dhrystone 2.1 benchmark -- part 2 (Proc_7, Proc_8, Func_1..Func_3).
 * Freestanding port for the Arty A7 VexRiscv reference design; see dhry.h.
 */

#include "dhry.h"
#include "platform.h"

void Proc_7(One_Fifty Int_1_Par_Val, One_Fifty Int_2_Par_Val,
            One_Fifty *Int_Par_Ref)
{
    One_Fifty Int_Loc;

    Int_Loc       = Int_1_Par_Val + 2;
    *Int_Par_Ref  = Int_2_Par_Val + Int_Loc;
}

void Proc_8(Arr_1_Dim Arr_1_Par_Ref, Arr_2_Dim Arr_2_Par_Ref,
            int Int_1_Par_Val, int Int_2_Par_Val)
{
    One_Fifty Int_Index;
    One_Fifty Int_Loc;

    Int_Loc                      = Int_1_Par_Val + 5;
    Arr_1_Par_Ref[Int_Loc]       = Int_2_Par_Val;
    Arr_1_Par_Ref[Int_Loc + 1]   = Arr_1_Par_Ref[Int_Loc];
    Arr_1_Par_Ref[Int_Loc + 30]  = Int_Loc;
    for (Int_Index = Int_Loc; Int_Index <= Int_Loc + 1; ++Int_Index)
        Arr_2_Par_Ref[Int_Loc][Int_Index] = Int_Loc;
    Arr_2_Par_Ref[Int_Loc][Int_Loc - 1]  += 1;
    Arr_2_Par_Ref[Int_Loc + 20][Int_Loc]  = Arr_1_Par_Ref[Int_Loc];
    Int_Glob = 5;
}

Enumeration Func_1(Capital_Letter Ch_1_Par_Val, Capital_Letter Ch_2_Par_Val)
{
    Capital_Letter Ch_1_Loc;
    Capital_Letter Ch_2_Loc;

    Ch_1_Loc = Ch_1_Par_Val;
    Ch_2_Loc = Ch_1_Loc;
    if (Ch_2_Loc != Ch_2_Par_Val)
        return Ident_1;
    Ch_1_Glob = Ch_1_Loc;
    return Ident_2;
}

Boolean Func_2(Str_30 Str_1_Par_Ref, Str_30 Str_2_Par_Ref)
{
    One_Thirty     Int_Loc;
    Capital_Letter Ch_Loc;

    Int_Loc = 2;
    Ch_Loc  = 'A';
    while (Int_Loc <= 2) {
        if (Func_1(Str_1_Par_Ref[Int_Loc], Str_2_Par_Ref[Int_Loc + 1]) == Ident_1) {
            Ch_Loc   = 'A';
            Int_Loc += 1;
        }
    }
    if (Ch_Loc >= 'W' && Ch_Loc < 'Z')
        Int_Loc = 7;
    if (Ch_Loc == 'R')
        return TRUE;
    if (strcmp(Str_1_Par_Ref, Str_2_Par_Ref) > 0) {
        Int_Loc += 7;
        Int_Glob = Int_Loc;
        return TRUE;
    }
    return FALSE;
}

Boolean Func_3(Enumeration Enum_Par_Val)
{
    Enumeration Enum_Loc;

    Enum_Loc = Enum_Par_Val;
    return (Enum_Loc == Ident_3) ? TRUE : FALSE;
}
