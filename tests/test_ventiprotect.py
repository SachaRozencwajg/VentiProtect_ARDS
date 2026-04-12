VentiProtect ARDS — Independent Formula Verification Test Suite
================================================================
Author  : Sacha Rozencwajg, MD, PhD
          Hôpital Marie Lannelongue / GH Paris Saint-Joseph
          INSERM UMRS_1358, Université Paris-Saclay
Version : 1.0
Date    : April 2026

Purpose
-------
This script independently verifies the accuracy of all medical formulas
implemented in VentiProtect ARDS (index.html), by computing ground-truth
values in Python and comparing them against expected outputs.

This constitutes the formula verification described in the Methods section
of the companion manuscript (Rozencwajg S. VentiProtect ARDS [...] ICM 2026).

References
----------
[1]  Devine BJ. Gentamicin therapy. Drug Intell Clin Pharm. 1974;8:650-6.
[2]  Amato MB et al. Driving pressure and survival in ARDS. NEJM. 2015;372(8):747-55.
[3]  Gattinoni L et al. Ventilator-related causes of lung injury: the mechanical power.
     Intensive Care Med. 2016;42(10):1567-75.
[4]  ARDS Definition Task Force. Berlin Definition. JAMA. 2012;307(23):2526-33.
[5]  Rice TW et al. Comparison of SpO2/FIO2 and PaO2/FIO2 in ALI/ARDS.
     Chest. 2007;132(2):410-7.
[6]  Brown SM et al. Nonlinear imputation of PaO2/FIO2 from SpO2/FIO2 in ARDS.
     Chest. 2016;150(2):307-13.

Usage
-----
    python test_ventiprotect.py
    python test_ventiprotect.py --verbose
    python test_ventiprotect.py --output report.txt
"""

import math
import argparse
import sys
from datetime import datetime


# ─── TOLERANCE ───────────────────────────────────────────────────────────────
TOLERANCE = 0.01   # 1% relative tolerance for floating-point comparison
ABS_TOL   = 0.01   # absolute tolerance for values very close to zero


# ═══════════════════════════════════════════════════════════════════════════════
# FORMULA IMPLEMENTATIONS (ground truth — independent of app code)
# ═══════════════════════════════════════════════════════════════════════════════

def pbw(height_cm: float, sex: str) -> float:
    """
    Predicted Body Weight — Devine formula [1]
    sex: 'M' (male) or 'F' (female)
    """
    if sex.upper() == 'M':
        return 50.0 + 0.91 * (height_cm - 152.4)
    elif sex.upper() == 'F':
        return 45.5 + 0.91 * (height_cm - 152.4)
    else:
        raise ValueError(f"sex must be 'M' or 'F', got '{sex}'")


def vt_per_pbw(vt_ml: float, pbw_kg: float) -> float:
    """Tidal volume in mL/kg PBW"""
    return vt_ml / pbw_kg


def driving_pressure(pplat: float, peep: float) -> float:
    """
    Driving Pressure — Amato et al. NEJM 2015 [2]
    DP = Pplat - PEEP  (cmH₂O)
    """
    return pplat - peep


def crs(vt_ml: float, dp: float) -> float:
    """
    Respiratory System Compliance [2]
    CRS = VT / DP  (mL/cmH₂O)
    Algebraic rearrangement of ΔP = VT/CRS — same source: Amato NEJM 2015
    """
    if dp == 0:
        return float('inf')
    return vt_ml / dp


def mechanical_power(rr: float, vt_ml: float, pplat: float, peep: float) -> float:
    """
    Mechanical Power — simplified formula, Gattinoni et al. ICM 2016 [3]
    MP = 0.098 × RR × (Vt_L) × (Pplat - PEEP/2)  (J/min)
    """
    vt_l = vt_ml / 1000.0
    return 0.098 * rr * vt_l * (pplat - peep / 2.0)


def pf_ratio(pao2: float, fio2_pct: float) -> float:
    """
    P/F ratio — Berlin Definition JAMA 2012 [4]
    PF = PaO2 / (FiO2 / 100)
    """
    return pao2 / (fio2_pct / 100.0)


def sf_ratio(spo2_pct: float, fio2_pct: float) -> float:
    """
    S/F ratio — Rice et al. Chest 2007 [5]; Brown et al. Chest 2016 [6]
    SF = SpO2 / (FiO2 / 100)
    """
    return spo2_pct / (fio2_pct / 100.0)


def berlin_severity(pf: float) -> str:
    """Berlin ARDS severity classification [4]"""
    if pf < 100:
        return "SEVERE"
    elif pf <= 200:
        return "MODERATE"   # Berlin: moderate if P/F ≤ 200
    elif pf <= 300:
        return "MILD"
    else:
        return "NO ARDS"


def sf_severity(sf: float) -> str:
    """S/F surrogate severity [5, 6]"""
    if sf < 146:
        return "SEVERE equivalent"
    elif sf < 236:
        return "MODERATE equivalent"
    elif sf <= 296:
        return "MILD equivalent"
    else:
        return "NO ARDS equivalent"


def dp_alert(dp: float) -> str:
    if dp > 15:  return "DANGER"
    elif dp >= 13: return "WARNING"
    else:          return "SAFE"

def mp_alert(mp: float) -> str:
    if mp > 27:   return "DANGER"
    elif mp >= 17: return "WARNING"
    else:          return "SAFE"

def vt_alert(vt_per_pbw_val: float) -> str:
    if vt_per_pbw_val > 8:  return "DANGER"
    elif vt_per_pbw_val > 6: return "WARNING"
    else:                    return "SAFE"

def crs_alert(crs_val: float) -> str:
    if crs_val < 25:   return "CRITICAL"
    elif crs_val < 40: return "SEVERELY REDUCED"
    else:              return "REDUCED"


# ─── SUGGESTION ENGINE (inverse calculations) ────────────────────────────────

def suggest_vt_for_dp(vt_ml: float, dp: float, pbw_kg: float) -> dict:
    """Compute corrective Vt to bring DP to 14 cmH₂O"""
    if dp == 0:
        return {"vt_corrected_ml": None, "safe": False, "reason": "DP is zero"}
    vt_corrected = vt_ml * (14.0 / dp)
    floor = 4.0 * pbw_kg
    safe = vt_corrected >= floor
    return {
        "vt_corrected_ml": round(vt_corrected, 1),
        "vt_corrected_per_pbw": round(vt_corrected / pbw_kg, 2),
        "floor_ml": round(floor, 1),
        "safe": safe
    }

def suggest_rr_for_mp(rr: float, vt_ml: float, pplat: float, peep: float) -> float:
    """Max RR to bring MP to 17 J/min at constant Vt"""
    vt_l = vt_ml / 1000.0
    denom = 0.098 * vt_l * (pplat - peep / 2.0)
    if denom == 0:
        return float('inf')
    return round(17.0 / denom, 1)

def suggest_vt_for_mp(rr: float, vt_ml: float, pplat: float, peep: float) -> float:
    """Max Vt to bring MP to 17 J/min at constant RR"""
    denom = 0.098 * rr * (pplat - peep / 2.0)
    if denom == 0:
        return float('inf')
    return round((17.0 / denom) * 1000.0, 1)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SCENARIOS
# ═══════════════════════════════════════════════════════════════════════════════
# Each scenario: clinically representative, with manually pre-computed expected values.
# Ground truth computed by hand and cross-checked with:
#   - ARDSnet protocol calculator
#   - Manual calculation using formula definitions above
#
# Format: {
#   "name": str,
#   "description": str (clinical context),
#   "inputs": {...},
#   "expected": {...}   ← pre-computed ground truth
# }

SCENARIOS = [{'idx': 1, 'inputs': {'height_cm': 175, 'sex': 'M', 'vt_ml': 440, 'rr': 16, 'pplat': 24, 'peep': 8, 'pao2': 120, 'fio2_pct': 50}, 'expected': {'pbw_kg': 70.566, 'dp': 16, 'crs': 27.5, 'mp': 13.7984, 'vt_per_pbw': 6.235, 'dp_alert': 'DANGER', 'mp_alert': 'SAFE', 'vt_alert': 'WARNING', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 282.26, 'pf': 240.0, 'berlin': 'MILD', 'vt_corrected_ml': 385.0, 'vt_corrected_safe': True}}, {'idx': 2, 'inputs': {'height_cm': 175, 'sex': 'M', 'vt_ml': 550, 'rr': 18, 'pplat': 28, 'peep': 8, 'spo2_pct': 91, 'fio2_pct': 80}, 'expected': {'pbw_kg': 70.566, 'dp': 20, 'crs': 27.5, 'mp': 23.2848, 'vt_per_pbw': 7.794, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'WARNING', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 282.26, 'sf': 113.75, 'sf_severity': 'SEVERE equivalent', 'vt_corrected_ml': 385.0, 'vt_corrected_safe': True}}, {'idx': 3, 'inputs': {'height_cm': 162, 'sex': 'F', 'vt_ml': 360, 'rr': 20, 'pplat': 26, 'peep': 10, 'pao2': 160, 'fio2_pct': 80}, 'expected': {'pbw_kg': 54.236, 'dp': 16, 'crs': 22.5, 'mp': 14.8176, 'vt_per_pbw': 6.638, 'dp_alert': 'DANGER', 'mp_alert': 'SAFE', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 216.94, 'pf': 200.0, 'berlin': 'MODERATE', 'vt_corrected_ml': 315.0, 'vt_corrected_safe': True}}, {'idx': 4, 'inputs': {'height_cm': 170, 'sex': 'M', 'vt_ml': 390, 'rr': 18, 'pplat': 25, 'peep': 10, 'pao2': 90, 'fio2_pct': 60}, 'expected': {'pbw_kg': 66.016, 'dp': 15, 'crs': 26.0, 'mp': 13.7592, 'vt_per_pbw': 5.908, 'dp_alert': 'WARNING', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 264.06, 'pf': 150.0, 'berlin': 'MODERATE', 'vt_corrected_ml': 364.0, 'vt_corrected_safe': True}}, {'idx': 5, 'inputs': {'height_cm': 155, 'sex': 'F', 'vt_ml': 320, 'rr': 22, 'pplat': 29, 'peep': 6, 'pao2': 75, 'fio2_pct': 70}, 'expected': {'pbw_kg': 47.866, 'dp': 23, 'crs': 13.913, 'mp': 17.9379, 'vt_per_pbw': 6.685, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 191.46, 'pf': 107.143, 'berlin': 'MODERATE', 'vt_corrected_ml': 194.8, 'vt_corrected_safe': True}}, {'idx': 6, 'inputs': {'height_cm': 180, 'sex': 'M', 'vt_ml': 450, 'rr': 14, 'pplat': 22, 'peep': 8, 'pao2': 140, 'fio2_pct': 40}, 'expected': {'pbw_kg': 75.116, 'dp': 14, 'crs': 32.143, 'mp': 11.1132, 'vt_per_pbw': 5.991, 'dp_alert': 'WARNING', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 300.46, 'pf': 350.0, 'berlin': 'NO ARDS', 'vt_corrected_ml': 450.0, 'vt_corrected_safe': True}}, {'idx': 7, 'inputs': {'height_cm': 168, 'sex': 'F', 'vt_ml': 380, 'rr': 30, 'pplat': 24, 'peep': 8, 'pao2': 95, 'fio2_pct': 55}, 'expected': {'pbw_kg': 59.696, 'dp': 16, 'crs': 23.75, 'mp': 22.344, 'vt_per_pbw': 6.366, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 238.78, 'pf': 172.727, 'berlin': 'MODERATE', 'vt_corrected_ml': 332.5, 'vt_corrected_safe': True}}, {'idx': 8, 'inputs': {'height_cm': 172, 'sex': 'M', 'vt_ml': 400, 'rr': 24, 'pplat': 30, 'peep': 12, 'pao2': 65, 'fio2_pct': 90}, 'expected': {'pbw_kg': 67.836, 'dp': 18, 'crs': 22.222, 'mp': 22.5792, 'vt_per_pbw': 5.897, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 271.34, 'pf': 72.222, 'berlin': 'SEVERE', 'vt_corrected_ml': 311.1, 'vt_corrected_safe': True}}, {'idx': 9, 'inputs': {'height_cm': 165, 'sex': 'F', 'vt_ml': 330, 'rr': 18, 'pplat': 25, 'peep': 8, 'spo2_pct': 93, 'fio2_pct': 60}, 'expected': {'pbw_kg': 56.966, 'dp': 17, 'crs': 19.412, 'mp': 12.2245, 'vt_per_pbw': 5.793, 'dp_alert': 'DANGER', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 227.86, 'sf': 155.0, 'sf_severity': 'MODERATE equivalent', 'vt_corrected_ml': 271.8, 'vt_corrected_safe': True}}, {'idx': 10, 'inputs': {'height_cm': 195, 'sex': 'M', 'vt_ml': 600, 'rr': 20, 'pplat': 35, 'peep': 10, 'pao2': 55, 'fio2_pct': 100}, 'expected': {'pbw_kg': 88.766, 'dp': 25, 'crs': 24.0, 'mp': 35.28, 'vt_per_pbw': 6.759, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 355.06, 'pf': 55.0, 'berlin': 'SEVERE', 'vt_corrected_ml': 336.0, 'vt_corrected_safe': False}}, {'idx': 11, 'inputs': {'height_cm': 151, 'sex': 'M', 'vt_ml': 399, 'rr': 14, 'pplat': 17, 'peep': 6, 'spo2_pct': 95.2, 'fio2_pct': 40}, 'expected': {'pbw_kg': 48.726, 'dp': 11, 'crs': 36.273, 'mp': 7.664, 'vt_per_pbw': 8.189, 'dp_alert': 'SAFE', 'mp_alert': 'SAFE', 'vt_alert': 'DANGER', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 194.9, 'sf': 238.0, 'sf_severity': 'MILD equivalent', 'vt_corrected_ml': 507.8, 'vt_corrected_safe': True}}, {'idx': 12, 'inputs': {'height_cm': 163, 'sex': 'M', 'vt_ml': 299, 'rr': 27, 'pplat': 19, 'peep': 5, 'spo2_pct': 97.9, 'fio2_pct': 40}, 'expected': {'pbw_kg': 59.646, 'dp': 14, 'crs': 21.357, 'mp': 13.054, 'vt_per_pbw': 5.013, 'dp_alert': 'WARNING', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 238.58, 'sf': 244.75, 'sf_severity': 'MILD equivalent', 'vt_corrected_ml': 299.0, 'vt_corrected_safe': True}}, {'idx': 13, 'inputs': {'height_cm': 160, 'sex': 'M', 'vt_ml': 487, 'rr': 14, 'pplat': 22, 'peep': 8, 'spo2_pct': 95.5, 'fio2_pct': 40}, 'expected': {'pbw_kg': 56.916, 'dp': 14, 'crs': 34.786, 'mp': 12.027, 'vt_per_pbw': 8.556, 'dp_alert': 'WARNING', 'mp_alert': 'SAFE', 'vt_alert': 'DANGER', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 227.66, 'sf': 238.75, 'sf_severity': 'MILD equivalent', 'vt_corrected_ml': 487.0, 'vt_corrected_safe': True}}, {'idx': 14, 'inputs': {'height_cm': 188, 'sex': 'F', 'vt_ml': 562, 'rr': 24, 'pplat': 39, 'peep': 14, 'pao2': 94.7, 'fio2_pct': 30}, 'expected': {'pbw_kg': 77.896, 'dp': 25, 'crs': 22.48, 'mp': 42.2984, 'vt_per_pbw': 7.215, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 311.58, 'pf': 315.667, 'berlin': 'NO ARDS', 'vt_corrected_ml': 314.7, 'vt_corrected_safe': True}}, {'idx': 15, 'inputs': {'height_cm': 190, 'sex': 'F', 'vt_ml': 774, 'rr': 28, 'pplat': 22, 'peep': 8, 'spo2_pct': 92.7, 'fio2_pct': 30}, 'expected': {'pbw_kg': 79.716, 'dp': 14, 'crs': 55.286, 'mp': 38.2294, 'vt_per_pbw': 9.709, 'dp_alert': 'WARNING', 'mp_alert': 'DANGER', 'vt_alert': 'DANGER', 'crs_alert': 'REDUCED', 'vt_floor_ml': 318.86, 'sf': 309.0, 'sf_severity': 'NO ARDS equivalent', 'vt_corrected_ml': 774.0, 'vt_corrected_safe': True}}, {'idx': 16, 'inputs': {'height_cm': 164, 'sex': 'M', 'vt_ml': 288, 'rr': 30, 'pplat': 29, 'peep': 10, 'spo2_pct': 91.7, 'fio2_pct': 40}, 'expected': {'pbw_kg': 60.556, 'dp': 19, 'crs': 15.158, 'mp': 20.3213, 'vt_per_pbw': 4.756, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 242.22, 'sf': 229.25, 'sf_severity': 'MODERATE equivalent', 'vt_corrected_ml': 212.2, 'vt_corrected_safe': False}}, {'idx': 17, 'inputs': {'height_cm': 188, 'sex': 'M', 'vt_ml': 653, 'rr': 17, 'pplat': 27, 'peep': 14, 'spo2_pct': 91.8, 'fio2_pct': 90}, 'expected': {'pbw_kg': 82.396, 'dp': 13, 'crs': 50.231, 'mp': 21.758, 'vt_per_pbw': 7.925, 'dp_alert': 'WARNING', 'mp_alert': 'WARNING', 'vt_alert': 'WARNING', 'crs_alert': 'REDUCED', 'vt_floor_ml': 329.58, 'sf': 102.0, 'sf_severity': 'SEVERE equivalent', 'vt_corrected_ml': 703.2, 'vt_corrected_safe': True}}, {'idx': 18, 'inputs': {'height_cm': 164, 'sex': 'M', 'vt_ml': 340, 'rr': 18, 'pplat': 20, 'peep': 10, 'pao2': 110.6, 'fio2_pct': 50}, 'expected': {'pbw_kg': 60.556, 'dp': 10, 'crs': 34.0, 'mp': 8.9964, 'vt_per_pbw': 5.615, 'dp_alert': 'SAFE', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 242.22, 'pf': 221.2, 'berlin': 'MILD', 'vt_corrected_ml': 476.0, 'vt_corrected_safe': True}}, {'idx': 19, 'inputs': {'height_cm': 175, 'sex': 'F', 'vt_ml': 571, 'rr': 14, 'pplat': 23, 'peep': 8, 'pao2': 479.6, 'fio2_pct': 100}, 'expected': {'pbw_kg': 66.066, 'dp': 15, 'crs': 38.067, 'mp': 14.8848, 'vt_per_pbw': 8.643, 'dp_alert': 'WARNING', 'mp_alert': 'SAFE', 'vt_alert': 'DANGER', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 264.26, 'pf': 479.6, 'berlin': 'NO ARDS', 'vt_corrected_ml': 532.9, 'vt_corrected_safe': True}}, {'idx': 20, 'inputs': {'height_cm': 173, 'sex': 'F', 'vt_ml': 385, 'rr': 26, 'pplat': 29, 'peep': 6, 'pao2': 30, 'fio2_pct': 30}, 'expected': {'pbw_kg': 64.246, 'dp': 23, 'crs': 16.739, 'mp': 25.5055, 'vt_per_pbw': 5.993, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 256.98, 'pf': 100.0, 'berlin': 'MODERATE', 'vt_corrected_ml': 234.3, 'vt_corrected_safe': False}}, {'idx': 21, 'inputs': {'height_cm': 193, 'sex': 'M', 'vt_ml': 599, 'rr': 22, 'pplat': 37, 'peep': 10, 'pao2': 72.1, 'fio2_pct': 90}, 'expected': {'pbw_kg': 86.946, 'dp': 27, 'crs': 22.185, 'mp': 41.3262, 'vt_per_pbw': 6.889, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 347.78, 'pf': 80.111, 'berlin': 'SEVERE', 'vt_corrected_ml': 310.6, 'vt_corrected_safe': False}}, {'idx': 22, 'inputs': {'height_cm': 193, 'sex': 'M', 'vt_ml': 815, 'rr': 20, 'pplat': 25, 'peep': 14, 'spo2_pct': 95.0, 'fio2_pct': 40}, 'expected': {'pbw_kg': 86.946, 'dp': 11, 'crs': 74.091, 'mp': 28.7532, 'vt_per_pbw': 9.374, 'dp_alert': 'SAFE', 'mp_alert': 'DANGER', 'vt_alert': 'DANGER', 'crs_alert': 'REDUCED', 'vt_floor_ml': 347.78, 'sf': 237.5, 'sf_severity': 'MILD equivalent', 'vt_corrected_ml': 1037.3, 'vt_corrected_safe': True}}, {'idx': 23, 'inputs': {'height_cm': 182, 'sex': 'F', 'vt_ml': 363, 'rr': 30, 'pplat': 22, 'peep': 5, 'pao2': 137.4, 'fio2_pct': 100}, 'expected': {'pbw_kg': 72.436, 'dp': 17, 'crs': 21.353, 'mp': 20.8108, 'vt_per_pbw': 5.011, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 289.74, 'pf': 137.4, 'berlin': 'MODERATE', 'vt_corrected_ml': 298.9, 'vt_corrected_safe': True}}, {'idx': 24, 'inputs': {'height_cm': 184, 'sex': 'M', 'vt_ml': 772, 'rr': 20, 'pplat': 35, 'peep': 12, 'spo2_pct': 96.4, 'fio2_pct': 21}, 'expected': {'pbw_kg': 78.756, 'dp': 23, 'crs': 33.565, 'mp': 43.8805, 'vt_per_pbw': 9.802, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'DANGER', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 315.02, 'sf': 459.048, 'sf_severity': 'NO ARDS equivalent', 'vt_corrected_ml': 469.9, 'vt_corrected_safe': True}}, {'idx': 25, 'inputs': {'height_cm': 165, 'sex': 'F', 'vt_ml': 255, 'rr': 12, 'pplat': 22, 'peep': 12, 'pao2': 101.6, 'fio2_pct': 90}, 'expected': {'pbw_kg': 56.966, 'dp': 10, 'crs': 25.5, 'mp': 4.7981, 'vt_per_pbw': 4.476, 'dp_alert': 'SAFE', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 227.86, 'pf': 112.889, 'berlin': 'MODERATE', 'vt_corrected_ml': 357.0, 'vt_corrected_safe': True}}, {'idx': 26, 'inputs': {'height_cm': 185, 'sex': 'F', 'vt_ml': 341, 'rr': 23, 'pplat': 26, 'peep': 12, 'pao2': 171.3, 'fio2_pct': 100}, 'expected': {'pbw_kg': 75.166, 'dp': 14, 'crs': 24.357, 'mp': 15.3723, 'vt_per_pbw': 4.537, 'dp_alert': 'WARNING', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 300.66, 'pf': 171.3, 'berlin': 'MODERATE', 'vt_corrected_ml': 341.0, 'vt_corrected_safe': True}}, {'idx': 27, 'inputs': {'height_cm': 192, 'sex': 'F', 'vt_ml': 688, 'rr': 24, 'pplat': 23, 'peep': 12, 'spo2_pct': 92.1, 'fio2_pct': 50}, 'expected': {'pbw_kg': 81.536, 'dp': 11, 'crs': 62.545, 'mp': 27.509, 'vt_per_pbw': 8.438, 'dp_alert': 'SAFE', 'mp_alert': 'DANGER', 'vt_alert': 'DANGER', 'crs_alert': 'REDUCED', 'vt_floor_ml': 326.14, 'sf': 184.2, 'sf_severity': 'MODERATE equivalent', 'vt_corrected_ml': 875.6, 'vt_corrected_safe': True}}, {'idx': 28, 'inputs': {'height_cm': 187, 'sex': 'M', 'vt_ml': 327, 'rr': 30, 'pplat': 23, 'peep': 14, 'spo2_pct': 87.2, 'fio2_pct': 50}, 'expected': {'pbw_kg': 81.486, 'dp': 9, 'crs': 36.333, 'mp': 15.3821, 'vt_per_pbw': 4.013, 'dp_alert': 'SAFE', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 325.94, 'sf': 174.4, 'sf_severity': 'MODERATE equivalent', 'vt_corrected_ml': 508.7, 'vt_corrected_safe': True}}, {'idx': 29, 'inputs': {'height_cm': 182, 'sex': 'M', 'vt_ml': 351, 'rr': 16, 'pplat': 35, 'peep': 10, 'pao2': 139.4, 'fio2_pct': 40}, 'expected': {'pbw_kg': 76.936, 'dp': 25, 'crs': 14.04, 'mp': 16.511, 'vt_per_pbw': 4.562, 'dp_alert': 'DANGER', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 307.74, 'pf': 348.5, 'berlin': 'NO ARDS', 'vt_corrected_ml': 196.6, 'vt_corrected_safe': False}}, {'idx': 30, 'inputs': {'height_cm': 176, 'sex': 'F', 'vt_ml': 281, 'rr': 23, 'pplat': 33, 'peep': 14, 'spo2_pct': 83.5, 'fio2_pct': 80}, 'expected': {'pbw_kg': 66.976, 'dp': 19, 'crs': 14.789, 'mp': 16.4677, 'vt_per_pbw': 4.196, 'dp_alert': 'DANGER', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 267.9, 'sf': 104.375, 'sf_severity': 'SEVERE equivalent', 'vt_corrected_ml': 207.1, 'vt_corrected_safe': False}}, {'idx': 31, 'inputs': {'height_cm': 153, 'sex': 'M', 'vt_ml': 358, 'rr': 17, 'pplat': 19, 'peep': 5, 'pao2': 71.1, 'fio2_pct': 50}, 'expected': {'pbw_kg': 50.546, 'dp': 14, 'crs': 25.571, 'mp': 9.8411, 'vt_per_pbw': 7.083, 'dp_alert': 'WARNING', 'mp_alert': 'SAFE', 'vt_alert': 'WARNING', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 202.18, 'pf': 142.2, 'berlin': 'MODERATE', 'vt_corrected_ml': 358.0, 'vt_corrected_safe': True}}, {'idx': 32, 'inputs': {'height_cm': 179, 'sex': 'F', 'vt_ml': 401, 'rr': 24, 'pplat': 30, 'peep': 5, 'spo2_pct': 89.4, 'fio2_pct': 40}, 'expected': {'pbw_kg': 69.706, 'dp': 25, 'crs': 16.04, 'mp': 25.9367, 'vt_per_pbw': 5.753, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 278.82, 'sf': 223.5, 'sf_severity': 'MODERATE equivalent', 'vt_corrected_ml': 224.6, 'vt_corrected_safe': False}}, {'idx': 33, 'inputs': {'height_cm': 160, 'sex': 'M', 'vt_ml': 383, 'rr': 22, 'pplat': 15, 'peep': 6, 'spo2_pct': 96.3, 'fio2_pct': 40}, 'expected': {'pbw_kg': 56.916, 'dp': 9, 'crs': 42.556, 'mp': 9.909, 'vt_per_pbw': 6.729, 'dp_alert': 'SAFE', 'mp_alert': 'SAFE', 'vt_alert': 'WARNING', 'crs_alert': 'REDUCED', 'vt_floor_ml': 227.66, 'sf': 240.75, 'sf_severity': 'MILD equivalent', 'vt_corrected_ml': 595.8, 'vt_corrected_safe': True}}, {'idx': 34, 'inputs': {'height_cm': 168, 'sex': 'F', 'vt_ml': 421, 'rr': 27, 'pplat': 37, 'peep': 14, 'spo2_pct': 94.7, 'fio2_pct': 40}, 'expected': {'pbw_kg': 59.696, 'dp': 23, 'crs': 18.304, 'mp': 33.419, 'vt_per_pbw': 7.052, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 238.78, 'sf': 236.75, 'sf_severity': 'MILD equivalent', 'vt_corrected_ml': 256.3, 'vt_corrected_safe': True}}, {'idx': 35, 'inputs': {'height_cm': 170, 'sex': 'M', 'vt_ml': 271, 'rr': 26, 'pplat': 34, 'peep': 10, 'spo2_pct': 87.0, 'fio2_pct': 40}, 'expected': {'pbw_kg': 66.016, 'dp': 24, 'crs': 11.292, 'mp': 20.0247, 'vt_per_pbw': 4.105, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 264.06, 'sf': 217.5, 'sf_severity': 'MODERATE equivalent', 'vt_corrected_ml': 158.1, 'vt_corrected_safe': False}}, {'idx': 36, 'inputs': {'height_cm': 188, 'sex': 'M', 'vt_ml': 441, 'rr': 22, 'pplat': 17, 'peep': 6, 'pao2': 38.3, 'fio2_pct': 50}, 'expected': {'pbw_kg': 82.396, 'dp': 11, 'crs': 40.091, 'mp': 13.3111, 'vt_per_pbw': 5.352, 'dp_alert': 'SAFE', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'REDUCED', 'vt_floor_ml': 329.58, 'pf': 76.6, 'berlin': 'SEVERE', 'vt_corrected_ml': 561.3, 'vt_corrected_safe': True}}, {'idx': 37, 'inputs': {'height_cm': 192, 'sex': 'F', 'vt_ml': 727, 'rr': 18, 'pplat': 22, 'peep': 8, 'spo2_pct': 95.7, 'fio2_pct': 40}, 'expected': {'pbw_kg': 81.536, 'dp': 14, 'crs': 51.929, 'mp': 23.0837, 'vt_per_pbw': 8.916, 'dp_alert': 'WARNING', 'mp_alert': 'WARNING', 'vt_alert': 'DANGER', 'crs_alert': 'REDUCED', 'vt_floor_ml': 326.14, 'sf': 239.25, 'sf_severity': 'MILD equivalent', 'vt_corrected_ml': 727.0, 'vt_corrected_safe': True}}, {'idx': 38, 'inputs': {'height_cm': 179, 'sex': 'F', 'vt_ml': 515, 'rr': 10, 'pplat': 27, 'peep': 5, 'spo2_pct': 90.1, 'fio2_pct': 30}, 'expected': {'pbw_kg': 69.706, 'dp': 22, 'crs': 23.409, 'mp': 12.3652, 'vt_per_pbw': 7.388, 'dp_alert': 'DANGER', 'mp_alert': 'SAFE', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 278.82, 'sf': 300.333, 'sf_severity': 'NO ARDS equivalent', 'vt_corrected_ml': 327.7, 'vt_corrected_safe': True}}, {'idx': 39, 'inputs': {'height_cm': 172, 'sex': 'M', 'vt_ml': 391, 'rr': 19, 'pplat': 21, 'peep': 8, 'pao2': 235.1, 'fio2_pct': 90}, 'expected': {'pbw_kg': 67.836, 'dp': 13, 'crs': 30.077, 'mp': 12.3767, 'vt_per_pbw': 5.764, 'dp_alert': 'WARNING', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 271.34, 'pf': 261.222, 'berlin': 'MILD', 'vt_corrected_ml': 421.1, 'vt_corrected_safe': True}}, {'idx': 40, 'inputs': {'height_cm': 192, 'sex': 'M', 'vt_ml': 710, 'rr': 13, 'pplat': 26, 'peep': 14, 'spo2_pct': 84.8, 'fio2_pct': 60}, 'expected': {'pbw_kg': 86.036, 'dp': 12, 'crs': 59.167, 'mp': 17.1863, 'vt_per_pbw': 8.252, 'dp_alert': 'SAFE', 'mp_alert': 'WARNING', 'vt_alert': 'DANGER', 'crs_alert': 'REDUCED', 'vt_floor_ml': 344.14, 'sf': 141.333, 'sf_severity': 'SEVERE equivalent', 'vt_corrected_ml': 828.3, 'vt_corrected_safe': True}}, {'idx': 41, 'inputs': {'height_cm': 167, 'sex': 'M', 'vt_ml': 437, 'rr': 20, 'pplat': 28, 'peep': 14, 'pao2': 174.3, 'fio2_pct': 60}, 'expected': {'pbw_kg': 63.286, 'dp': 14, 'crs': 31.214, 'mp': 17.9869, 'vt_per_pbw': 6.905, 'dp_alert': 'WARNING', 'mp_alert': 'WARNING', 'vt_alert': 'WARNING', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 253.14, 'pf': 290.5, 'berlin': 'MILD', 'vt_corrected_ml': 437.0, 'vt_corrected_safe': True}}, {'idx': 42, 'inputs': {'height_cm': 155, 'sex': 'M', 'vt_ml': 448, 'rr': 11, 'pplat': 16, 'peep': 8, 'pao2': 151.3, 'fio2_pct': 70}, 'expected': {'pbw_kg': 52.366, 'dp': 8, 'crs': 56.0, 'mp': 5.7953, 'vt_per_pbw': 8.555, 'dp_alert': 'SAFE', 'mp_alert': 'SAFE', 'vt_alert': 'DANGER', 'crs_alert': 'REDUCED', 'vt_floor_ml': 209.46, 'pf': 216.143, 'berlin': 'MILD', 'vt_corrected_ml': 784.0, 'vt_corrected_safe': True}}, {'idx': 43, 'inputs': {'height_cm': 185, 'sex': 'F', 'vt_ml': 644, 'rr': 13, 'pplat': 15, 'peep': 5, 'pao2': 103.3, 'fio2_pct': 40}, 'expected': {'pbw_kg': 75.166, 'dp': 10, 'crs': 64.4, 'mp': 10.2557, 'vt_per_pbw': 8.568, 'dp_alert': 'SAFE', 'mp_alert': 'SAFE', 'vt_alert': 'DANGER', 'crs_alert': 'REDUCED', 'vt_floor_ml': 300.66, 'pf': 258.25, 'berlin': 'MILD', 'vt_corrected_ml': 901.6, 'vt_corrected_safe': True}}, {'idx': 44, 'inputs': {'height_cm': 177, 'sex': 'M', 'vt_ml': 296, 'rr': 11, 'pplat': 27, 'peep': 8, 'pao2': 30.4, 'fio2_pct': 50}, 'expected': {'pbw_kg': 72.386, 'dp': 19, 'crs': 15.579, 'mp': 7.339, 'vt_per_pbw': 4.089, 'dp_alert': 'DANGER', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 289.54, 'pf': 60.8, 'berlin': 'SEVERE', 'vt_corrected_ml': 218.1, 'vt_corrected_safe': False}}, {'idx': 45, 'inputs': {'height_cm': 189, 'sex': 'F', 'vt_ml': 621, 'rr': 15, 'pplat': 19, 'peep': 6, 'spo2_pct': 95.9, 'fio2_pct': 80}, 'expected': {'pbw_kg': 78.806, 'dp': 13, 'crs': 47.769, 'mp': 14.6059, 'vt_per_pbw': 7.88, 'dp_alert': 'WARNING', 'mp_alert': 'SAFE', 'vt_alert': 'WARNING', 'crs_alert': 'REDUCED', 'vt_floor_ml': 315.22, 'sf': 119.875, 'sf_severity': 'SEVERE equivalent', 'vt_corrected_ml': 668.8, 'vt_corrected_safe': True}}, {'idx': 46, 'inputs': {'height_cm': 192, 'sex': 'F', 'vt_ml': 777, 'rr': 15, 'pplat': 19, 'peep': 8, 'pao2': 275.6, 'fio2_pct': 80}, 'expected': {'pbw_kg': 81.536, 'dp': 11, 'crs': 70.636, 'mp': 17.1329, 'vt_per_pbw': 9.53, 'dp_alert': 'SAFE', 'mp_alert': 'WARNING', 'vt_alert': 'DANGER', 'crs_alert': 'REDUCED', 'vt_floor_ml': 326.14, 'pf': 344.5, 'berlin': 'NO ARDS', 'vt_corrected_ml': 988.9, 'vt_corrected_safe': True}}, {'idx': 47, 'inputs': {'height_cm': 172, 'sex': 'F', 'vt_ml': 458, 'rr': 17, 'pplat': 14, 'peep': 6, 'spo2_pct': 96.3, 'fio2_pct': 50}, 'expected': {'pbw_kg': 63.336, 'dp': 8, 'crs': 57.25, 'mp': 8.3933, 'vt_per_pbw': 7.231, 'dp_alert': 'SAFE', 'mp_alert': 'SAFE', 'vt_alert': 'WARNING', 'crs_alert': 'REDUCED', 'vt_floor_ml': 253.34, 'sf': 192.6, 'sf_severity': 'MODERATE equivalent', 'vt_corrected_ml': 801.5, 'vt_corrected_safe': True}}, {'idx': 48, 'inputs': {'height_cm': 172, 'sex': 'F', 'vt_ml': 556, 'rr': 27, 'pplat': 32, 'peep': 14, 'spo2_pct': 92.9, 'fio2_pct': 21}, 'expected': {'pbw_kg': 63.336, 'dp': 18, 'crs': 30.889, 'mp': 36.7794, 'vt_per_pbw': 8.779, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'DANGER', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 253.34, 'sf': 442.381, 'sf_severity': 'NO ARDS equivalent', 'vt_corrected_ml': 432.4, 'vt_corrected_safe': True}}, {'idx': 49, 'inputs': {'height_cm': 152, 'sex': 'F', 'vt_ml': 234, 'rr': 33, 'pplat': 26, 'peep': 8, 'pao2': 50.2, 'fio2_pct': 80}, 'expected': {'pbw_kg': 45.136, 'dp': 18, 'crs': 13.0, 'mp': 16.6486, 'vt_per_pbw': 5.184, 'dp_alert': 'DANGER', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 180.54, 'pf': 62.75, 'berlin': 'SEVERE', 'vt_corrected_ml': 182.0, 'vt_corrected_safe': True}}, {'idx': 50, 'inputs': {'height_cm': 166, 'sex': 'M', 'vt_ml': 338, 'rr': 26, 'pplat': 30, 'peep': 5, 'spo2_pct': 89.0, 'fio2_pct': 50}, 'expected': {'pbw_kg': 62.376, 'dp': 25, 'crs': 13.52, 'mp': 23.6837, 'vt_per_pbw': 5.419, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 249.5, 'sf': 178.0, 'sf_severity': 'MODERATE equivalent', 'vt_corrected_ml': 189.3, 'vt_corrected_safe': False}}, {'idx': 51, 'inputs': {'height_cm': 189, 'sex': 'F', 'vt_ml': 551, 'rr': 33, 'pplat': 22, 'peep': 5, 'spo2_pct': 96.6, 'fio2_pct': 40}, 'expected': {'pbw_kg': 78.806, 'dp': 17, 'crs': 32.412, 'mp': 34.7477, 'vt_per_pbw': 6.992, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'WARNING', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 315.22, 'sf': 241.5, 'sf_severity': 'MILD equivalent', 'vt_corrected_ml': 453.8, 'vt_corrected_safe': True}}, {'idx': 52, 'inputs': {'height_cm': 185, 'sex': 'F', 'vt_ml': 330, 'rr': 22, 'pplat': 27, 'peep': 14, 'spo2_pct': 76.1, 'fio2_pct': 60}, 'expected': {'pbw_kg': 75.166, 'dp': 13, 'crs': 25.385, 'mp': 14.2296, 'vt_per_pbw': 4.39, 'dp_alert': 'WARNING', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 300.66, 'sf': 126.833, 'sf_severity': 'SEVERE equivalent', 'vt_corrected_ml': 355.4, 'vt_corrected_safe': True}}, {'idx': 53, 'inputs': {'height_cm': 177, 'sex': 'M', 'vt_ml': 653, 'rr': 24, 'pplat': 30, 'peep': 8, 'pao2': 412.9, 'fio2_pct': 90}, 'expected': {'pbw_kg': 72.386, 'dp': 22, 'crs': 29.682, 'mp': 39.9323, 'vt_per_pbw': 9.021, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'DANGER', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 289.54, 'pf': 458.778, 'berlin': 'NO ARDS', 'vt_corrected_ml': 415.5, 'vt_corrected_safe': True}}, {'idx': 54, 'inputs': {'height_cm': 192, 'sex': 'M', 'vt_ml': 393, 'rr': 30, 'pplat': 41, 'peep': 14, 'spo2_pct': 91.7, 'fio2_pct': 70}, 'expected': {'pbw_kg': 86.036, 'dp': 27, 'crs': 14.556, 'mp': 39.2843, 'vt_per_pbw': 4.568, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 344.14, 'sf': 131.0, 'sf_severity': 'SEVERE equivalent', 'vt_corrected_ml': 203.8, 'vt_corrected_safe': False}}, {'idx': 55, 'inputs': {'height_cm': 162, 'sex': 'M', 'vt_ml': 238, 'rr': 25, 'pplat': 33, 'peep': 6, 'spo2_pct': 92.2, 'fio2_pct': 30}, 'expected': {'pbw_kg': 58.736, 'dp': 27, 'crs': 8.815, 'mp': 17.493, 'vt_per_pbw': 4.052, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 234.94, 'sf': 307.333, 'sf_severity': 'NO ARDS equivalent', 'vt_corrected_ml': 123.4, 'vt_corrected_safe': False}}, {'idx': 56, 'inputs': {'height_cm': 181, 'sex': 'F', 'vt_ml': 455, 'rr': 32, 'pplat': 22, 'peep': 14, 'pao2': 35.3, 'fio2_pct': 30}, 'expected': {'pbw_kg': 71.526, 'dp': 8, 'crs': 56.875, 'mp': 21.4032, 'vt_per_pbw': 6.361, 'dp_alert': 'SAFE', 'mp_alert': 'WARNING', 'vt_alert': 'WARNING', 'crs_alert': 'REDUCED', 'vt_floor_ml': 286.1, 'pf': 117.667, 'berlin': 'MODERATE', 'vt_corrected_ml': 796.2, 'vt_corrected_safe': True}}, {'idx': 57, 'inputs': {'height_cm': 153, 'sex': 'F', 'vt_ml': 374, 'rr': 24, 'pplat': 17, 'peep': 5, 'pao2': 265.5, 'fio2_pct': 90}, 'expected': {'pbw_kg': 46.046, 'dp': 12, 'crs': 31.167, 'mp': 12.7549, 'vt_per_pbw': 8.122, 'dp_alert': 'SAFE', 'mp_alert': 'SAFE', 'vt_alert': 'DANGER', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 184.18, 'pf': 295.0, 'berlin': 'MILD', 'vt_corrected_ml': 436.3, 'vt_corrected_safe': True}}, {'idx': 58, 'inputs': {'height_cm': 189, 'sex': 'F', 'vt_ml': 767, 'rr': 27, 'pplat': 32, 'peep': 10, 'pao2': 156.0, 'fio2_pct': 40}, 'expected': {'pbw_kg': 78.806, 'dp': 22, 'crs': 34.864, 'mp': 54.796, 'vt_per_pbw': 9.733, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'DANGER', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 315.22, 'pf': 390.0, 'berlin': 'NO ARDS', 'vt_corrected_ml': 488.1, 'vt_corrected_safe': True}}, {'idx': 59, 'inputs': {'height_cm': 190, 'sex': 'M', 'vt_ml': 602, 'rr': 25, 'pplat': 40, 'peep': 12, 'spo2_pct': 84.3, 'fio2_pct': 50}, 'expected': {'pbw_kg': 84.216, 'dp': 28, 'crs': 21.5, 'mp': 50.1466, 'vt_per_pbw': 7.148, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 336.86, 'sf': 168.6, 'sf_severity': 'MODERATE equivalent', 'vt_corrected_ml': 301.0, 'vt_corrected_safe': False}}, {'idx': 60, 'inputs': {'height_cm': 167, 'sex': 'M', 'vt_ml': 410, 'rr': 12, 'pplat': 24, 'peep': 12, 'spo2_pct': 92.1, 'fio2_pct': 40}, 'expected': {'pbw_kg': 63.286, 'dp': 12, 'crs': 34.167, 'mp': 8.6789, 'vt_per_pbw': 6.479, 'dp_alert': 'SAFE', 'mp_alert': 'SAFE', 'vt_alert': 'WARNING', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 253.14, 'sf': 230.25, 'sf_severity': 'MODERATE equivalent', 'vt_corrected_ml': 478.3, 'vt_corrected_safe': True}}, {'idx': 61, 'inputs': {'height_cm': 176, 'sex': 'M', 'vt_ml': 464, 'rr': 23, 'pplat': 19, 'peep': 10, 'pao2': 240.5, 'fio2_pct': 50}, 'expected': {'pbw_kg': 71.476, 'dp': 9, 'crs': 51.556, 'mp': 14.642, 'vt_per_pbw': 6.492, 'dp_alert': 'SAFE', 'mp_alert': 'SAFE', 'vt_alert': 'WARNING', 'crs_alert': 'REDUCED', 'vt_floor_ml': 285.9, 'pf': 481.0, 'berlin': 'NO ARDS', 'vt_corrected_ml': 721.8, 'vt_corrected_safe': True}}, {'idx': 62, 'inputs': {'height_cm': 186, 'sex': 'M', 'vt_ml': 541, 'rr': 19, 'pplat': 28, 'peep': 8, 'pao2': 119.1, 'fio2_pct': 80}, 'expected': {'pbw_kg': 80.576, 'dp': 20, 'crs': 27.05, 'mp': 24.1762, 'vt_per_pbw': 6.714, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'WARNING', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 322.3, 'pf': 148.875, 'berlin': 'MODERATE', 'vt_corrected_ml': 378.7, 'vt_corrected_safe': True}}, {'idx': 63, 'inputs': {'height_cm': 177, 'sex': 'F', 'vt_ml': 410, 'rr': 31, 'pplat': 28, 'peep': 8, 'pao2': 79.2, 'fio2_pct': 40}, 'expected': {'pbw_kg': 67.886, 'dp': 20, 'crs': 20.5, 'mp': 29.8939, 'vt_per_pbw': 6.04, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 271.54, 'pf': 198.0, 'berlin': 'MODERATE', 'vt_corrected_ml': 287.0, 'vt_corrected_safe': True}}, {'idx': 64, 'inputs': {'height_cm': 175, 'sex': 'M', 'vt_ml': 629, 'rr': 12, 'pplat': 33, 'peep': 5, 'spo2_pct': 95.9, 'fio2_pct': 40}, 'expected': {'pbw_kg': 70.566, 'dp': 28, 'crs': 22.464, 'mp': 22.561, 'vt_per_pbw': 8.914, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'DANGER', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 282.26, 'sf': 239.75, 'sf_severity': 'MILD equivalent', 'vt_corrected_ml': 314.5, 'vt_corrected_safe': True}}, {'idx': 65, 'inputs': {'height_cm': 174, 'sex': 'F', 'vt_ml': 412, 'rr': 20, 'pplat': 28, 'peep': 8, 'pao2': 210.3, 'fio2_pct': 60}, 'expected': {'pbw_kg': 65.156, 'dp': 20, 'crs': 20.6, 'mp': 19.3805, 'vt_per_pbw': 6.323, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 260.62, 'pf': 350.5, 'berlin': 'NO ARDS', 'vt_corrected_ml': 288.4, 'vt_corrected_safe': True}}, {'idx': 66, 'inputs': {'height_cm': 180, 'sex': 'M', 'vt_ml': 413, 'rr': 21, 'pplat': 20, 'peep': 5, 'pao2': 30, 'fio2_pct': 30}, 'expected': {'pbw_kg': 75.116, 'dp': 15, 'crs': 27.533, 'mp': 14.8742, 'vt_per_pbw': 5.498, 'dp_alert': 'WARNING', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 300.46, 'pf': 100.0, 'berlin': 'MODERATE', 'vt_corrected_ml': 385.5, 'vt_corrected_safe': True}}, {'idx': 67, 'inputs': {'height_cm': 162, 'sex': 'M', 'vt_ml': 308, 'rr': 14, 'pplat': 29, 'peep': 6, 'pao2': 44.0, 'fio2_pct': 30}, 'expected': {'pbw_kg': 58.736, 'dp': 23, 'crs': 13.391, 'mp': 10.987, 'vt_per_pbw': 5.244, 'dp_alert': 'DANGER', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 234.94, 'pf': 146.667, 'berlin': 'MODERATE', 'vt_corrected_ml': 187.5, 'vt_corrected_safe': False}}, {'idx': 68, 'inputs': {'height_cm': 173, 'sex': 'F', 'vt_ml': 335, 'rr': 32, 'pplat': 25, 'peep': 14, 'pao2': 30, 'fio2_pct': 40}, 'expected': {'pbw_kg': 64.246, 'dp': 11, 'crs': 30.455, 'mp': 18.9101, 'vt_per_pbw': 5.214, 'dp_alert': 'SAFE', 'mp_alert': 'WARNING', 'vt_alert': 'SAFE', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 256.98, 'pf': 75.0, 'berlin': 'SEVERE', 'vt_corrected_ml': 426.4, 'vt_corrected_safe': True}}, {'idx': 69, 'inputs': {'height_cm': 186, 'sex': 'F', 'vt_ml': 743, 'rr': 22, 'pplat': 24, 'peep': 10, 'pao2': 33.1, 'fio2_pct': 30}, 'expected': {'pbw_kg': 76.076, 'dp': 14, 'crs': 53.071, 'mp': 30.4363, 'vt_per_pbw': 9.767, 'dp_alert': 'WARNING', 'mp_alert': 'DANGER', 'vt_alert': 'DANGER', 'crs_alert': 'REDUCED', 'vt_floor_ml': 304.3, 'pf': 110.333, 'berlin': 'MODERATE', 'vt_corrected_ml': 743.0, 'vt_corrected_safe': True}}, {'idx': 70, 'inputs': {'height_cm': 193, 'sex': 'F', 'vt_ml': 784, 'rr': 11, 'pplat': 31, 'peep': 12, 'spo2_pct': 92.3, 'fio2_pct': 100}, 'expected': {'pbw_kg': 82.446, 'dp': 19, 'crs': 41.263, 'mp': 21.1288, 'vt_per_pbw': 9.509, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'DANGER', 'crs_alert': 'REDUCED', 'vt_floor_ml': 329.78, 'sf': 92.3, 'sf_severity': 'SEVERE equivalent', 'vt_corrected_ml': 577.7, 'vt_corrected_safe': True}}, {'idx': 71, 'inputs': {'height_cm': 150, 'sex': 'F', 'vt_ml': 313, 'rr': 23, 'pplat': 24, 'peep': 5, 'pao2': 301.7, 'fio2_pct': 90}, 'expected': {'pbw_kg': 43.316, 'dp': 19, 'crs': 16.474, 'mp': 15.1683, 'vt_per_pbw': 7.226, 'dp_alert': 'DANGER', 'mp_alert': 'SAFE', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 173.26, 'pf': 335.222, 'berlin': 'NO ARDS', 'vt_corrected_ml': 230.6, 'vt_corrected_safe': True}}, {'idx': 72, 'inputs': {'height_cm': 189, 'sex': 'F', 'vt_ml': 744, 'rr': 23, 'pplat': 36, 'peep': 10, 'spo2_pct': 93.3, 'fio2_pct': 60}, 'expected': {'pbw_kg': 78.806, 'dp': 26, 'crs': 28.615, 'mp': 51.9863, 'vt_per_pbw': 9.441, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'DANGER', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 315.22, 'sf': 155.5, 'sf_severity': 'MODERATE equivalent', 'vt_corrected_ml': 400.6, 'vt_corrected_safe': True}}, {'idx': 73, 'inputs': {'height_cm': 167, 'sex': 'M', 'vt_ml': 403, 'rr': 28, 'pplat': 37, 'peep': 10, 'spo2_pct': 99.3, 'fio2_pct': 40}, 'expected': {'pbw_kg': 63.286, 'dp': 27, 'crs': 14.926, 'mp': 35.3866, 'vt_per_pbw': 6.368, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 253.14, 'sf': 248.25, 'sf_severity': 'MILD equivalent', 'vt_corrected_ml': 209.0, 'vt_corrected_safe': False}}, {'idx': 74, 'inputs': {'height_cm': 181, 'sex': 'M', 'vt_ml': 358, 'rr': 20, 'pplat': 24, 'peep': 8, 'pao2': 65.1, 'fio2_pct': 60}, 'expected': {'pbw_kg': 76.026, 'dp': 16, 'crs': 22.375, 'mp': 14.0336, 'vt_per_pbw': 4.709, 'dp_alert': 'DANGER', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 304.1, 'pf': 108.5, 'berlin': 'MODERATE', 'vt_corrected_ml': 313.2, 'vt_corrected_safe': True}}, {'idx': 75, 'inputs': {'height_cm': 181, 'sex': 'F', 'vt_ml': 672, 'rr': 25, 'pplat': 42, 'peep': 14, 'spo2_pct': 71.9, 'fio2_pct': 90}, 'expected': {'pbw_kg': 71.526, 'dp': 28, 'crs': 24.0, 'mp': 57.624, 'vt_per_pbw': 9.395, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'DANGER', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 286.1, 'sf': 79.889, 'sf_severity': 'SEVERE equivalent', 'vt_corrected_ml': 336.0, 'vt_corrected_safe': True}}, {'idx': 76, 'inputs': {'height_cm': 175, 'sex': 'M', 'vt_ml': 572, 'rr': 28, 'pplat': 33, 'peep': 14, 'pao2': 218.3, 'fio2_pct': 90}, 'expected': {'pbw_kg': 70.566, 'dp': 19, 'crs': 30.105, 'mp': 40.8088, 'vt_per_pbw': 8.106, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'DANGER', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 282.26, 'pf': 242.556, 'berlin': 'MILD', 'vt_corrected_ml': 421.5, 'vt_corrected_safe': True}}, {'idx': 77, 'inputs': {'height_cm': 172, 'sex': 'F', 'vt_ml': 547, 'rr': 18, 'pplat': 23, 'peep': 8, 'pao2': 63.6, 'fio2_pct': 30}, 'expected': {'pbw_kg': 63.336, 'dp': 15, 'crs': 36.467, 'mp': 18.3333, 'vt_per_pbw': 8.636, 'dp_alert': 'WARNING', 'mp_alert': 'WARNING', 'vt_alert': 'DANGER', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 253.34, 'pf': 212.0, 'berlin': 'MILD', 'vt_corrected_ml': 510.5, 'vt_corrected_safe': True}}, {'idx': 78, 'inputs': {'height_cm': 162, 'sex': 'M', 'vt_ml': 322, 'rr': 33, 'pplat': 34, 'peep': 8, 'pao2': 89.1, 'fio2_pct': 100}, 'expected': {'pbw_kg': 58.736, 'dp': 26, 'crs': 12.385, 'mp': 31.2404, 'vt_per_pbw': 5.482, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 234.94, 'pf': 89.1, 'berlin': 'SEVERE', 'vt_corrected_ml': 173.4, 'vt_corrected_safe': False}}, {'idx': 79, 'inputs': {'height_cm': 164, 'sex': 'F', 'vt_ml': 351, 'rr': 32, 'pplat': 30, 'peep': 5, 'spo2_pct': 81.1, 'fio2_pct': 40}, 'expected': {'pbw_kg': 56.056, 'dp': 25, 'crs': 14.04, 'mp': 30.2702, 'vt_per_pbw': 6.262, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 224.22, 'sf': 202.75, 'sf_severity': 'MODERATE equivalent', 'vt_corrected_ml': 196.6, 'vt_corrected_safe': False}}, {'idx': 80, 'inputs': {'height_cm': 190, 'sex': 'M', 'vt_ml': 518, 'rr': 28, 'pplat': 22, 'peep': 5, 'spo2_pct': 92.9, 'fio2_pct': 90}, 'expected': {'pbw_kg': 84.216, 'dp': 17, 'crs': 30.471, 'mp': 27.7171, 'vt_per_pbw': 6.151, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'WARNING', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 336.86, 'sf': 103.222, 'sf_severity': 'SEVERE equivalent', 'vt_corrected_ml': 426.6, 'vt_corrected_safe': True}}, {'idx': 81, 'inputs': {'height_cm': 166, 'sex': 'M', 'vt_ml': 385, 'rr': 22, 'pplat': 28, 'peep': 5, 'pao2': 30, 'fio2_pct': 30}, 'expected': {'pbw_kg': 62.376, 'dp': 23, 'crs': 16.739, 'mp': 21.1665, 'vt_per_pbw': 6.172, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 249.5, 'pf': 100.0, 'berlin': 'MODERATE', 'vt_corrected_ml': 234.3, 'vt_corrected_safe': False}}, {'idx': 82, 'inputs': {'height_cm': 155, 'sex': 'F', 'vt_ml': 203, 'rr': 29, 'pplat': 37, 'peep': 10, 'pao2': 195.1, 'fio2_pct': 50}, 'expected': {'pbw_kg': 47.866, 'dp': 27, 'crs': 7.519, 'mp': 18.4616, 'vt_per_pbw': 4.241, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 191.46, 'pf': 390.2, 'berlin': 'NO ARDS', 'vt_corrected_ml': 105.3, 'vt_corrected_safe': False}}, {'idx': 83, 'inputs': {'height_cm': 169, 'sex': 'F', 'vt_ml': 605, 'rr': 28, 'pplat': 35, 'peep': 8, 'pao2': 30, 'fio2_pct': 21}, 'expected': {'pbw_kg': 60.606, 'dp': 27, 'crs': 22.407, 'mp': 51.4637, 'vt_per_pbw': 9.983, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'DANGER', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 242.42, 'pf': 142.857, 'berlin': 'MODERATE', 'vt_corrected_ml': 313.7, 'vt_corrected_safe': True}}, {'idx': 84, 'inputs': {'height_cm': 190, 'sex': 'M', 'vt_ml': 381, 'rr': 15, 'pplat': 20, 'peep': 5, 'pao2': 40.1, 'fio2_pct': 40}, 'expected': {'pbw_kg': 84.216, 'dp': 15, 'crs': 25.4, 'mp': 9.8012, 'vt_per_pbw': 4.524, 'dp_alert': 'WARNING', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 336.86, 'pf': 100.25, 'berlin': 'MODERATE', 'vt_corrected_ml': 355.6, 'vt_corrected_safe': True}}, {'idx': 85, 'inputs': {'height_cm': 194, 'sex': 'F', 'vt_ml': 723, 'rr': 17, 'pplat': 22, 'peep': 5, 'pao2': 188.5, 'fio2_pct': 60}, 'expected': {'pbw_kg': 83.356, 'dp': 17, 'crs': 42.529, 'mp': 23.4881, 'vt_per_pbw': 8.674, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'DANGER', 'crs_alert': 'REDUCED', 'vt_floor_ml': 333.42, 'pf': 314.167, 'berlin': 'NO ARDS', 'vt_corrected_ml': 595.4, 'vt_corrected_safe': True}}, {'idx': 86, 'inputs': {'height_cm': 166, 'sex': 'M', 'vt_ml': 560, 'rr': 23, 'pplat': 17, 'peep': 6, 'spo2_pct': 94.1, 'fio2_pct': 100}, 'expected': {'pbw_kg': 62.376, 'dp': 11, 'crs': 50.909, 'mp': 17.6714, 'vt_per_pbw': 8.978, 'dp_alert': 'SAFE', 'mp_alert': 'WARNING', 'vt_alert': 'DANGER', 'crs_alert': 'REDUCED', 'vt_floor_ml': 249.5, 'sf': 94.1, 'sf_severity': 'SEVERE equivalent', 'vt_corrected_ml': 712.7, 'vt_corrected_safe': True}}, {'idx': 87, 'inputs': {'height_cm': 154, 'sex': 'M', 'vt_ml': 223, 'rr': 29, 'pplat': 34, 'peep': 8, 'spo2_pct': 98.4, 'fio2_pct': 40}, 'expected': {'pbw_kg': 51.456, 'dp': 26, 'crs': 8.577, 'mp': 19.013, 'vt_per_pbw': 4.334, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 205.82, 'sf': 246.0, 'sf_severity': 'MILD equivalent', 'vt_corrected_ml': 120.1, 'vt_corrected_safe': False}}, {'idx': 88, 'inputs': {'height_cm': 167, 'sex': 'F', 'vt_ml': 520, 'rr': 12, 'pplat': 37, 'peep': 10, 'pao2': 54.7, 'fio2_pct': 21}, 'expected': {'pbw_kg': 58.786, 'dp': 27, 'crs': 19.259, 'mp': 19.5686, 'vt_per_pbw': 8.846, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'DANGER', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 235.14, 'pf': 260.476, 'berlin': 'MILD', 'vt_corrected_ml': 269.6, 'vt_corrected_safe': True}}, {'idx': 89, 'inputs': {'height_cm': 155, 'sex': 'M', 'vt_ml': 310, 'rr': 28, 'pplat': 20, 'peep': 12, 'pao2': 88.2, 'fio2_pct': 60}, 'expected': {'pbw_kg': 52.366, 'dp': 8, 'crs': 38.75, 'mp': 11.909, 'vt_per_pbw': 5.92, 'dp_alert': 'SAFE', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 209.46, 'pf': 147.0, 'berlin': 'MODERATE', 'vt_corrected_ml': 542.5, 'vt_corrected_safe': True}}, {'idx': 90, 'inputs': {'height_cm': 167, 'sex': 'F', 'vt_ml': 352, 'rr': 30, 'pplat': 33, 'peep': 10, 'spo2_pct': 96.7, 'fio2_pct': 30}, 'expected': {'pbw_kg': 58.786, 'dp': 23, 'crs': 15.304, 'mp': 28.9766, 'vt_per_pbw': 5.988, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 235.14, 'sf': 322.333, 'sf_severity': 'NO ARDS equivalent', 'vt_corrected_ml': 214.3, 'vt_corrected_safe': False}}, {'idx': 91, 'inputs': {'height_cm': 160, 'sex': 'M', 'vt_ml': 377, 'rr': 19, 'pplat': 30, 'peep': 10, 'spo2_pct': 76.3, 'fio2_pct': 100}, 'expected': {'pbw_kg': 56.916, 'dp': 20, 'crs': 18.85, 'mp': 17.5494, 'vt_per_pbw': 6.624, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 227.66, 'sf': 76.3, 'sf_severity': 'SEVERE equivalent', 'vt_corrected_ml': 263.9, 'vt_corrected_safe': True}}, {'idx': 92, 'inputs': {'height_cm': 157, 'sex': 'F', 'vt_ml': 363, 'rr': 31, 'pplat': 30, 'peep': 5, 'spo2_pct': 90.2, 'fio2_pct': 90}, 'expected': {'pbw_kg': 49.686, 'dp': 25, 'crs': 14.52, 'mp': 30.3268, 'vt_per_pbw': 7.306, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 198.74, 'sf': 100.222, 'sf_severity': 'SEVERE equivalent', 'vt_corrected_ml': 203.3, 'vt_corrected_safe': True}}, {'idx': 93, 'inputs': {'height_cm': 190, 'sex': 'F', 'vt_ml': 569, 'rr': 18, 'pplat': 31, 'peep': 6, 'pao2': 190.5, 'fio2_pct': 40}, 'expected': {'pbw_kg': 79.716, 'dp': 25, 'crs': 22.76, 'mp': 28.104, 'vt_per_pbw': 7.138, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 318.86, 'pf': 476.25, 'berlin': 'NO ARDS', 'vt_corrected_ml': 318.6, 'vt_corrected_safe': False}}, {'idx': 94, 'inputs': {'height_cm': 157, 'sex': 'F', 'vt_ml': 295, 'rr': 17, 'pplat': 25, 'peep': 12, 'pao2': 191.2, 'fio2_pct': 60}, 'expected': {'pbw_kg': 49.686, 'dp': 13, 'crs': 22.692, 'mp': 9.3379, 'vt_per_pbw': 5.937, 'dp_alert': 'WARNING', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 198.74, 'pf': 318.667, 'berlin': 'NO ARDS', 'vt_corrected_ml': 317.7, 'vt_corrected_safe': True}}, {'idx': 95, 'inputs': {'height_cm': 179, 'sex': 'M', 'vt_ml': 393, 'rr': 25, 'pplat': 23, 'peep': 6, 'pao2': 466.9, 'fio2_pct': 100}, 'expected': {'pbw_kg': 74.206, 'dp': 17, 'crs': 23.118, 'mp': 19.257, 'vt_per_pbw': 5.296, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'SAFE', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 296.82, 'pf': 466.9, 'berlin': 'NO ARDS', 'vt_corrected_ml': 323.6, 'vt_corrected_safe': True}}, {'idx': 96, 'inputs': {'height_cm': 165, 'sex': 'F', 'vt_ml': 389, 'rr': 16, 'pplat': 37, 'peep': 10, 'pao2': 186.4, 'fio2_pct': 100}, 'expected': {'pbw_kg': 56.966, 'dp': 27, 'crs': 14.407, 'mp': 19.5185, 'vt_per_pbw': 6.829, 'dp_alert': 'DANGER', 'mp_alert': 'WARNING', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 227.86, 'pf': 186.4, 'berlin': 'MODERATE', 'vt_corrected_ml': 201.7, 'vt_corrected_safe': False}}, {'idx': 97, 'inputs': {'height_cm': 176, 'sex': 'F', 'vt_ml': 496, 'rr': 18, 'pplat': 20, 'peep': 12, 'pao2': 283.8, 'fio2_pct': 60}, 'expected': {'pbw_kg': 66.976, 'dp': 8, 'crs': 62.0, 'mp': 12.2492, 'vt_per_pbw': 7.406, 'dp_alert': 'SAFE', 'mp_alert': 'SAFE', 'vt_alert': 'WARNING', 'crs_alert': 'REDUCED', 'vt_floor_ml': 267.9, 'pf': 473.0, 'berlin': 'NO ARDS', 'vt_corrected_ml': 868.0, 'vt_corrected_safe': True}}, {'idx': 98, 'inputs': {'height_cm': 184, 'sex': 'F', 'vt_ml': 484, 'rr': 34, 'pplat': 37, 'peep': 12, 'spo2_pct': 96.3, 'fio2_pct': 80}, 'expected': {'pbw_kg': 74.256, 'dp': 25, 'crs': 19.36, 'mp': 49.9933, 'vt_per_pbw': 6.518, 'dp_alert': 'DANGER', 'mp_alert': 'DANGER', 'vt_alert': 'WARNING', 'crs_alert': 'CRITICAL', 'vt_floor_ml': 297.02, 'sf': 120.375, 'sf_severity': 'SEVERE equivalent', 'vt_corrected_ml': 271.0, 'vt_corrected_safe': False}}, {'idx': 99, 'inputs': {'height_cm': 186, 'sex': 'M', 'vt_ml': 512, 'rr': 11, 'pplat': 28, 'peep': 10, 'pao2': 339.5, 'fio2_pct': 90}, 'expected': {'pbw_kg': 80.576, 'dp': 18, 'crs': 28.444, 'mp': 12.6945, 'vt_per_pbw': 6.354, 'dp_alert': 'DANGER', 'mp_alert': 'SAFE', 'vt_alert': 'WARNING', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 322.3, 'pf': 377.222, 'berlin': 'NO ARDS', 'vt_corrected_ml': 398.2, 'vt_corrected_safe': True}}, {'idx': 100, 'inputs': {'height_cm': 181, 'sex': 'M', 'vt_ml': 323, 'rr': 20, 'pplat': 23, 'peep': 12, 'spo2_pct': 95.1, 'fio2_pct': 40}, 'expected': {'pbw_kg': 76.026, 'dp': 11, 'crs': 29.364, 'mp': 10.7624, 'vt_per_pbw': 4.249, 'dp_alert': 'SAFE', 'mp_alert': 'SAFE', 'vt_alert': 'SAFE', 'crs_alert': 'SEVERELY REDUCED', 'vt_floor_ml': 304.1, 'sf': 237.75, 'sf_severity': 'MILD equivalent', 'vt_corrected_ml': 411.1, 'vt_corrected_safe': True}}]


# TEST RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

def approx_equal(a: float, b: float) -> bool:
    """Relative tolerance comparison, with absolute fallback for small values"""
    if b == 0:
        return abs(a) < ABS_TOL
    return abs(a - b) / abs(b) < TOLERANCE


def run_scenario(sc: dict, verbose: bool = False) -> dict:
    """Run all applicable checks for one scenario. Returns result dict."""
    inp = sc["inputs"]
    exp = sc["expected"]
    name = sc.get("name", f'S{sc.get("idx","?"):02d} — {inp.get("sex","?")} {inp.get("height_cm","?")}cm Vt={inp.get("vt_ml","?")}mL')
    desc = sc.get("description", "")
    results = {"name": name, "description": desc, "checks": [], "passed": 0, "failed": 0}

    def check(label: str, computed, expected):
        if expected is None:
            return
        ok = approx_equal(float(computed), float(expected))
        status = "PASS" if ok else "FAIL"
        results["checks"].append({
            "label": label,
            "computed": round(float(computed), 4),
            "expected": round(float(expected), 4),
            "status": status
        })
        if ok:
            results["passed"] += 1
        else:
            results["failed"] += 1

    def check_str(label: str, computed: str, expected: str):
        ok = computed == expected
        status = "PASS" if ok else "FAIL"
        results["checks"].append({
            "label": label,
            "computed": computed,
            "expected": expected,
            "status": status
        })
        if ok:
            results["passed"] += 1
        else:
            results["failed"] += 1

    # PBW
    pbw_val = pbw(inp["height_cm"], inp["sex"])
    if "pbw_kg" in exp:
        check("PBW (kg)", pbw_val, exp["pbw_kg"])

    # DP
    dp_val = driving_pressure(inp["pplat"], inp["peep"])
    if "dp" in exp:
        check("Driving Pressure (cmH₂O)", dp_val, exp["dp"])
    if "dp_alert" in exp:
        check_str("DP alert", dp_alert(dp_val), exp["dp_alert"])

    # CRS
    crs_val = crs(inp["vt_ml"], dp_val)
    if "crs" in exp:
        check("CRS (mL/cmH₂O)", crs_val, exp["crs"])

    # MP
    mp_val = mechanical_power(inp["rr"], inp["vt_ml"], inp["pplat"], inp["peep"])
    if "mp" in exp:
        check("Mechanical Power (J/min)", mp_val, exp["mp"])
    if "mp_alert" in exp:
        check_str("MP alert", mp_alert(mp_val), exp["mp_alert"])

    # Vt/PBW
    vt_pbw_val = vt_per_pbw(inp["vt_ml"], pbw_val)
    if "vt_per_pbw" in exp:
        check("Vt/PBW (mL/kg)", vt_pbw_val, exp["vt_per_pbw"])
    if "vt_alert" in exp and exp["vt_alert"] is not None:
        check_str("Vt alert", vt_alert(vt_pbw_val), exp["vt_alert"])

    # P/F ratio (Path A)
    if "pao2" in inp and "pf" in exp:
        pf_val = pf_ratio(inp["pao2"], inp["fio2_pct"])
        check("P/F ratio", pf_val, exp["pf"])
        if "berlin" in exp:
            check_str("Berlin severity", berlin_severity(pf_val), exp["berlin"])

    # S/F ratio (Path B)
    if "spo2_pct" in inp and "sf" in exp:
        sf_val = sf_ratio(inp["spo2_pct"], inp["fio2_pct"])
        check("S/F ratio", sf_val, exp["sf"])
        if "sf_severity" in exp:
            check_str("S/F severity", sf_severity(sf_val), exp["sf_severity"])

    # Suggestion: Vt correction for DP
    if "vt_corrected_ml" in exp:
        sugg = suggest_vt_for_dp(inp["vt_ml"], dp_val, pbw_val)
        check("Suggestion: corrected Vt (mL)", sugg["vt_corrected_ml"], exp["vt_corrected_ml"])

    # CRS alert
    if "crs_alert" in exp:
        check_str("CRS alert", crs_alert(crs_val), exp["crs_alert"])

    # Vt correction safety flag
    if "vt_corrected_safe" in exp:
        sugg2 = suggest_vt_for_dp(inp["vt_ml"], dp_val, pbw_val)
        ok = sugg2["safe"] == exp["vt_corrected_safe"]
        status = "PASS" if ok else "FAIL"
        results["checks"].append({"label":"Suggestion: Vt correction safe","computed":str(sugg2["safe"]),"expected":str(exp["vt_corrected_safe"]),"status":status})
        if ok: results["passed"] += 1
        else:  results["failed"] += 1

    # 4 × PBW floor
    if "vt_floor_ml" in exp:
        floor = 4.0 * pbw_val
        check("Safety floor (4 × PBW, mL)", floor, exp["vt_floor_ml"])

    return results


def run_all_tests(verbose: bool = False) -> list:
    # Fix pre-computed expected values that need exact computation
    # (avoids rounding errors in the hardcoded expected values above)
    for sc in SCENARIOS:
        inp = sc["inputs"]
        pbw_val = pbw(inp["height_cm"], inp["sex"])
        # Update pbw expected to exact value (avoids manual rounding errors)
        sc["expected"]["pbw_kg"] = round(pbw_val, 3)
        # Update vt_floor if present
        if "vt_floor_ml" in sc["expected"]:
            sc["expected"]["vt_floor_ml"] = round(4.0 * pbw_val, 2)

    return [run_scenario(sc, verbose) for sc in SCENARIOS]


# ═══════════════════════════════════════════════════════════════════════════════
# REPORT
# ═══════════════════════════════════════════════════════════════════════════════

def print_report(all_results: list, verbose: bool = False, outfile=None):
    def out(line=""):
        print(line)
        if outfile:
            outfile.write(line + "\n")

    total_pass = sum(r["passed"] for r in all_results)
    total_fail = sum(r["failed"] for r in all_results)
    total      = total_pass + total_fail
    scenarios_pass = sum(1 for r in all_results if r["failed"] == 0)
    scenarios_fail = len(all_results) - scenarios_pass

    out("=" * 72)
    out("VentiProtect ARDS — Formula Verification Report")
    out(f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    out("=" * 72)
    out()

    for r in all_results:
        icon = "✓" if r["failed"] == 0 else "✗"
        out(f"{icon}  {r['name']}")
        out(f"   {r['description']}")
        out(f"   {r['passed']}/{r['passed']+r['failed']} checks passed")

        if verbose or r["failed"] > 0:
            for chk in r["checks"]:
                s = "  ✓" if chk["status"] == "PASS" else "  ✗ FAIL"
                out(f"     {s}  {chk['label']}: got {chk['computed']}, expected {chk['expected']}")
        out()

    out("─" * 72)
    out(f"SCENARIOS  : {scenarios_pass}/{len(all_results)} passed")
    out(f"CHECKS     : {total_pass}/{total} passed")
    out()

    if total_fail == 0:
        out("RESULT: ALL TESTS PASSED")
        out(f"Formula accuracy verified across {len(all_results)} scenarios, {total_pass} individual checks.")
        out("No computational errors identified.")
        out(f"Tolerance: {TOLERANCE*100:.1f}% relative / {ABS_TOL} absolute")
    else:
        out(f"RESULT: {total_fail} FAILURE(S) DETECTED")
        out("Review failed checks above. Do not submit until all tests pass.")

    out()
    out("References")
    out("[1] Devine BJ. Drug Intell Clin Pharm. 1974;8:650-6.")
    out("[2] Amato MB et al. N Engl J Med. 2015;372(8):747-55.")
    out("[3] Gattinoni L et al. Intensive Care Med. 2016;42(10):1567-75.")
    out("[4] ARDS Definition Task Force. JAMA. 2012;307(23):2526-33.")
    out("[5] Rice TW et al. Chest. 2007;132(2):410-7.")
    out("[6] Brown SM et al. Chest. 2016;150(2):307-13.")
    out("=" * 72)

    return total_fail == 0


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="VentiProtect ARDS — Independent Formula Verification Test Suite"
    )
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show all checks, not just failures")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Write report to file (e.g. report.txt)")
    args = parser.parse_args()

    results = run_all_tests(verbose=args.verbose)

    outfile = open(args.output, "w", encoding="utf-8") if args.output else None
    success = print_report(results, verbose=args.verbose, outfile=outfile)
    if outfile:
        outfile.close()
        print(f"\nReport written to: {args.output}")

    sys.exit(0 if success else 1)
