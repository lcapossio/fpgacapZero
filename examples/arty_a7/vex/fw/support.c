/* SPDX-License-Identifier: Apache-2.0
 * Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
 *
 * Freestanding string/memory helpers for the VexRiscv Dhrystone firmware.
 * The firmware links -nostdlib, so the few libc routines Dhrystone needs (and
 * the memcpy the compiler emits for struct copies) are provided here under
 * their standard names. Deliberately simple (byte-at-a-time): they run inside
 * Dhrystone's measured string handling, so they are intentionally the same on
 * every build rather than an optimised libc.
 */

#include "platform.h"

void *memcpy(void *dst, const void *src, size_t n)
{
    unsigned char *d = (unsigned char *)dst;
    const unsigned char *s = (const unsigned char *)src;
    while (n--)
        *d++ = *s++;
    return dst;
}

char *strcpy(char *dst, const char *src)
{
    char *d = dst;
    while ((*d++ = *src++) != '\0')
        ;
    return dst;
}

int strcmp(const char *a, const char *b)
{
    while (*a != '\0' && *a == *b) {
        a++;
        b++;
    }
    return (int)(unsigned char)*a - (int)(unsigned char)*b;
}
