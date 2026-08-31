/* SPDX-License-Identifier: Apache-2.0
 * Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
 *
 * Dhrystone 2.1 benchmark -- data types and declarations.
 *
 * The Dhrystone benchmark was written by Reinhold P. Weicker (1988) and is
 * freely distributable. This is a faithful, freestanding re-implementation of
 * the standard version 2.1 for the Arty A7 VexRiscv reference design: it keeps
 * the benchmark's types, globals, and the Proc_*/Func_* procedure mix exactly,
 * but replaces the host I/O (malloc / scanf / printf / clock()) with a fixed
 * run count, static record storage, an MMIO cycle counter, and result stores
 * to the shared AXI slave (see platform.h). The computed workload -- and hence
 * the DMIPS number -- matches the standard benchmark.
 */

#ifndef FCAPZ_DHRY_H
#define FCAPZ_DHRY_H

/* Number of times the main measurement loop runs. Chosen so the 32-bit MMIO
 * cycle counter (100 MHz) cannot wrap during a run; override at build time
 * with -DNUMBER_OF_RUNS=<n>. The host reads the actual cycle delta and clock
 * rate back, so this only needs to be "large enough to be stable". */
#ifndef NUMBER_OF_RUNS
#define NUMBER_OF_RUNS 100000
#endif

#define TRUE  1
#define FALSE 0
#define Null  0

typedef enum { Ident_1, Ident_2, Ident_3, Ident_4, Ident_5 } Enumeration;

typedef int  One_Thirty;
typedef int  One_Fifty;
typedef char Capital_Letter;
typedef int  Boolean;
typedef char Str_30[31];
typedef int  Arr_1_Dim[50];
typedef int  Arr_2_Dim[50][50];

typedef struct record {
    struct record *Ptr_Comp;
    Enumeration    Discr;
    union {
        struct {
            Enumeration Enum_Comp;
            int         Int_Comp;
            char        Str_Comp[31];
        } var_1;
        struct {
            Enumeration E_Comp_2;
            char        Str_2_Comp[31];
        } var_2;
        struct {
            char Ch_1_Comp;
            char Ch_2_Comp;
        } var_3;
    } variant;
} Rec_Type, *Rec_Pointer;

/* struct copy -- the compiler lowers this to a memcpy (support.c). */
#define structassign(d, s) ((d) = (s))

/* Procedures / functions (dhry_1.c + dhry_2.c). */
void        Proc_1(Rec_Pointer Ptr_Val_Par);
void        Proc_2(One_Fifty *Int_Par_Ref);
void        Proc_3(Rec_Pointer *Ptr_Ref_Par);
void        Proc_4(void);
void        Proc_5(void);
void        Proc_6(Enumeration Enum_Val_Par, Enumeration *Enum_Ref_Par);
void        Proc_7(One_Fifty Int_1_Par_Val, One_Fifty Int_2_Par_Val,
                   One_Fifty *Int_Par_Ref);
void        Proc_8(Arr_1_Dim Arr_1_Par_Ref, Arr_2_Dim Arr_2_Par_Ref,
                   int Int_1_Par_Val, int Int_2_Par_Val);
Enumeration Func_1(Capital_Letter Ch_1_Par_Val, Capital_Letter Ch_2_Par_Val);
Boolean     Func_2(Str_30 Str_1_Par_Ref, Str_30 Str_2_Par_Ref);
Boolean     Func_3(Enumeration Enum_Par_Val);

/* Shared globals (defined in dhry_1.c). */
extern Rec_Pointer Ptr_Glob, Next_Ptr_Glob;
extern int         Int_Glob;
extern Boolean     Bool_Glob;
extern char        Ch_1_Glob, Ch_2_Glob;
extern int         Arr_1_Glob[50];
extern int         Arr_2_Glob[50][50];

#endif /* FCAPZ_DHRY_H */
