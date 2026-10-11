/* Modified for the lemmsar/lame maintenance fork on 2026-10-11. */

/*
 *      MP3 Huffman table selection, ARM NEON intrinsics
 *
 *      Copyright (c) 2026 The LAME project
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Library General Public
 * License as published by the Free Software Foundation; either
 * version 2 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.     See the GNU
 * Library General Public License for more details.
 *
 * You should have received a copy of the GNU Library General Public
 * License along with this library; if not, write to the
 * Free Software Foundation, Inc., 59 Temple Place - Suite 330,
 * Boston, MA 02111-1307, USA.
 */

/**
 * \file
 * \internal
 * \brief The NEON form of the Huffman bit count for the escape tables
 *        (count_bit_esc_neon()).
 */


#ifdef HAVE_CONFIG_H
# include <config.h>
#endif

#include "lame.h"
#include "machine.h"
#include "encoder.h"
#include "util.h"
#include "lame_intrin.h"


#ifdef HAVE_NEON_INTRINSICS

#include <arm_neon.h>

/*
 *  Backported from upstream SVN r7051 for this ARM64-only opt-in build.
 *  Source: https://svn.code.sf.net/p/lame/svn/!svn/bc/7051/trunk/lame/
 *          libmp3lame/vector/neon_choose_table.c
 *
 *  This fork enables the routine only with --enable-neon on AArch64. The
 *  caller is selected at build time; the default build uses the scalar
 *  counting loop. This NEON path has no runtime CPU dispatch and is not
 *  built for 32-bit ARM.
 *
 *  Raspberry Pi performance has not been measured. Upstream benchmark
 *  results do not establish a speedup for this build on the target device.
 *
 *  Each pair of nonnegative quantized values contributes the table index
 *  min(x, 15) * 16 + min(y, 15). Multiplying by (16, 1) and adding adjacent
 *  lanes forms the indices; values >= 15 are counted separately for the
 *  escape bits. The arithmetic does not narrow the values to sixteen bits.
 *
 *  It reads [ix, end), whose length is even, and touches nothing else. The
 *  remainder is consumed pair by pair exactly as in the scalar loop.
 */

/* Sum adjacent products: {a0+a1, a2+a3}. */
static int32x2_t
fold_pairs(int32x4_t v)
{
    return vpadd_s32(vget_low_s32(v), vget_high_s32(v));
}


unsigned int
count_bit_esc_neon(const int *ix, const int *const end,
                   const uint32_t * const largetbl, unsigned int *const nclamped)
{
    /* Load a constant array to avoid vector-initializer compiler extensions. */
    static const int32_t mul16[4] = { 16, 1, 16, 1 };
    int32x4_t const vmul = vld1q_s32(mul16);
    int32x4_t const v14 = vdupq_n_s32(14);
    int32x4_t const v15 = vdupq_n_s32(15);
    int32x4_t clamps = vdupq_n_s32(0);
    int32x2_t clamps2;
    unsigned int sum = 0;
    unsigned int n;

    while (end - ix >= 8) {
        int32x4_t const a = vld1q_s32(ix);
        int32x4_t const b = vld1q_s32(ix + 4);
        int32x2_t const ia = fold_pairs(vmulq_s32(vminq_s32(a, v15), vmul));
        int32x2_t const ib = fold_pairs(vmulq_s32(vminq_s32(b, v15), vmul));

        /* A true comparison is -1 in a signed lane, so subtracting it
           increments the count without a per-lane select. */
        clamps = vsubq_s32(clamps, vreinterpretq_s32_u32(vcgtq_s32(a, v14)));
        clamps = vsubq_s32(clamps, vreinterpretq_s32_u32(vcgtq_s32(b, v14)));

        sum += largetbl[vget_lane_s32(ia, 0)];
        sum += largetbl[vget_lane_s32(ia, 1)];
        sum += largetbl[vget_lane_s32(ib, 0)];
        sum += largetbl[vget_lane_s32(ib, 1)];
        ix += 8;
    }
    /* Four lane counters into one.  A region holds far too few values for a
       32-bit lane to come near overflowing. */
    clamps2 = vadd_s32(vget_low_s32(clamps), vget_high_s32(clamps));
    clamps2 = vpadd_s32(clamps2, clamps2);
    n = (unsigned int) vget_lane_s32(clamps2, 0);

    while (ix < end) {
        unsigned int x = *ix++;
        unsigned int y = *ix++;

        if (x >= 15u) {
            x = 15u;
            ++n;
        }
        if (y >= 15u) {
            y = 15u;
            ++n;
        }
        sum += largetbl[(x << 4u) + y];
    }
    *nclamped = n;
    return sum;
}


#endif /* HAVE_NEON_INTRINSICS */
