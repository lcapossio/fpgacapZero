/* SPDX-License-Identifier: Apache-2.0
 * Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
 *
 * Dhrystone 2.1 benchmark -- part 1 (globals, main driver, Proc_1..Proc_6).
 * Freestanding port for the Arty A7 VexRiscv reference design; see dhry.h for
 * provenance. The benchmark mix is the standard one; only the driver's setup
 * and reporting are adapted to bare metal (static storage, MMIO cycle timing,
 * results published to the shared AXI slave, re-armed by the host go flag).
 */

#include "dhry.h"
#include "platform.h"

/* Global Variables */
Rec_Pointer Ptr_Glob, Next_Ptr_Glob;
int         Int_Glob;
Boolean     Bool_Glob;
char        Ch_1_Glob, Ch_2_Glob;
int         Arr_1_Glob[50];
int         Arr_2_Glob[50][50];

/* Static storage replacing the two malloc()'d records in the standard code. */
static Rec_Type Rec_Storage_1, Rec_Storage_2;

static void Dhrystone_Run(void)
{
    One_Fifty   Int_1_Loc;
    One_Fifty   Int_2_Loc;
    One_Fifty   Int_3_Loc;
    char        Ch_Index;
    Enumeration Enum_Loc;
    Str_30      Str_1_Loc;
    Str_30      Str_2_Loc;
    int         Run_Index;
    uint32_t    start_cycles, end_cycles;

    /* Initializations */
    Next_Ptr_Glob = &Rec_Storage_1;
    Ptr_Glob      = &Rec_Storage_2;

    Ptr_Glob->Ptr_Comp                = Next_Ptr_Glob;
    Ptr_Glob->Discr                   = Ident_1;
    Ptr_Glob->variant.var_1.Enum_Comp = Ident_3;
    Ptr_Glob->variant.var_1.Int_Comp  = 40;
    strcpy(Ptr_Glob->variant.var_1.Str_Comp, "DHRYSTONE PROGRAM, SOME STRING");
    strcpy(Str_1_Loc, "DHRYSTONE PROGRAM, 1'ST STRING");

    Arr_2_Glob[8][7] = 10;
    /* Was missing in published program: an appropriate initialisation of the
     * two array components. Left as in the standard 2.1 driver. */

    start_cycles = plat_cycles();

    for (Run_Index = 1; Run_Index <= NUMBER_OF_RUNS; ++Run_Index) {
        Proc_5();
        Proc_4();
        /* Ch_1_Glob == 'A', Ch_2_Glob == 'B', Bool_Glob == true */
        Int_1_Loc = 2;
        Int_2_Loc = 3;
        strcpy(Str_2_Loc, "DHRYSTONE PROGRAM, 2'ND STRING");
        Enum_Loc  = Ident_2;
        Bool_Glob = !Func_2(Str_1_Loc, Str_2_Loc);
        while (Int_1_Loc < Int_2_Loc) {
            Int_3_Loc = 5 * Int_1_Loc - Int_2_Loc;
            Proc_7(Int_1_Loc, Int_2_Loc, &Int_3_Loc);
            Int_1_Loc += 1;
        }
        Proc_8(Arr_1_Glob, Arr_2_Glob, Int_1_Loc, Int_3_Loc);
        Proc_1(Ptr_Glob);
        for (Ch_Index = 'A'; Ch_Index <= Ch_2_Glob; ++Ch_Index) {
            if (Enum_Loc == Func_1(Ch_Index, 'C')) {
                Proc_6(Ident_1, &Enum_Loc);
                strcpy(Str_2_Loc, "DHRYSTONE PROGRAM, 3'RD STRING");
                Int_2_Loc = Run_Index;
                Int_Glob  = Run_Index;
            }
        }
        Int_2_Loc = Int_2_Loc * Int_1_Loc;
        Int_1_Loc = Int_2_Loc / Int_3_Loc;
        Int_2_Loc = 7 * (Int_2_Loc - Int_3_Loc) - Int_1_Loc;
        Proc_2(&Int_1_Loc);
    }

    end_cycles = plat_cycles();

    /* Checksum the benchmark's final global state. Beyond a sanity value for
     * the host, consuming these results is what keeps the optimiser from
     * deleting the (otherwise side-effect-free) measured loop. */
    uint32_t checksum = (uint32_t)Int_Glob
                      + (uint32_t)Bool_Glob
                      + (uint32_t)(unsigned char)Ch_1_Glob
                      + (uint32_t)(unsigned char)Ch_2_Glob
                      + (uint32_t)Arr_1_Glob[8]
                      + (uint32_t)Arr_2_Glob[8][7]
                      + (uint32_t)Ptr_Glob->variant.var_1.Int_Comp;

    /* Publish to the shared slave; the host reads it back over EJTAG-AXI and
     * computes DMIPS = runs / (cycles / clock_hz) / 1757. */
    plat_publish((uint32_t)NUMBER_OF_RUNS, end_cycles - start_cycles, checksum);
}

int main(void)
{
    for (;;) {
        while (plat_go() == 0u)
            ;               /* idle: read-only polling, bus stays quiet */
        Dhrystone_Run();
        while (plat_go() != 0u)
            ;               /* wait for the host to lower go before re-running */
    }
}

void Proc_1(Rec_Pointer Ptr_Val_Par)
{
    Rec_Pointer Next_Record = Ptr_Val_Par->Ptr_Comp;

    structassign(*Ptr_Val_Par->Ptr_Comp, *Ptr_Glob);
    Ptr_Val_Par->variant.var_1.Int_Comp = 5;
    Next_Record->variant.var_1.Int_Comp = Ptr_Val_Par->variant.var_1.Int_Comp;
    Next_Record->Ptr_Comp               = Ptr_Val_Par->Ptr_Comp;
    Proc_3(&Next_Record->Ptr_Comp);
    if (Next_Record->Discr == Ident_1) {
        Next_Record->variant.var_1.Int_Comp = 6;
        Proc_6(Ptr_Val_Par->variant.var_1.Enum_Comp,
               &Next_Record->variant.var_1.Enum_Comp);
        Next_Record->Ptr_Comp = Ptr_Glob->Ptr_Comp;
        Proc_7(Next_Record->variant.var_1.Int_Comp, 10,
               &Next_Record->variant.var_1.Int_Comp);
    } else {
        structassign(*Ptr_Val_Par, *Ptr_Val_Par->Ptr_Comp);
    }
}

void Proc_2(One_Fifty *Int_Par_Ref)
{
    One_Fifty   Int_Loc;
    Enumeration Enum_Loc;

    Int_Loc  = *Int_Par_Ref + 10;
    Enum_Loc = Ident_1;
    do {
        if (Ch_1_Glob == 'A') {
            Int_Loc      -= 1;
            *Int_Par_Ref  = Int_Loc - Int_Glob;
            Enum_Loc      = Ident_1;
        }
    } while (Enum_Loc != Ident_1);
}

void Proc_3(Rec_Pointer *Ptr_Ref_Par)
{
    if (Ptr_Glob != Null)
        *Ptr_Ref_Par = Ptr_Glob->Ptr_Comp;
    Proc_7(10, Int_Glob, &Ptr_Glob->variant.var_1.Int_Comp);
}

void Proc_4(void)
{
    Boolean Bool_Loc;

    Bool_Loc  = Ch_1_Glob == 'A';
    Bool_Glob = Bool_Loc | Bool_Glob;
    Ch_2_Glob = 'B';
}

void Proc_5(void)
{
    Ch_1_Glob = 'A';
    Bool_Glob = FALSE;
}

void Proc_6(Enumeration Enum_Val_Par, Enumeration *Enum_Ref_Par)
{
    *Enum_Ref_Par = Enum_Val_Par;
    if (!Func_3(Enum_Val_Par))
        *Enum_Ref_Par = Ident_4;
    switch (Enum_Val_Par) {
    case Ident_1:
        *Enum_Ref_Par = Ident_1;
        break;
    case Ident_2:
        *Enum_Ref_Par = (Int_Glob > 100) ? Ident_1 : Ident_4;
        break;
    case Ident_3:
        *Enum_Ref_Par = Ident_2;
        break;
    case Ident_4:
        break;
    case Ident_5:
        *Enum_Ref_Par = Ident_3;
        break;
    }
}
