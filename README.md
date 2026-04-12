# VentiProtect ARDS

**Lung-Protective Ventilation Titration Assistant**

VentiProtect ARDS is a real-time, active titration assistant designed to optimize lung-protective ventilation for patients with medical Acute Respiratory Distress Syndrome (ARDS) at ICU admission. 

## Features

- **Real-Time Calculation**: Dynamic computation of clinical parameters instantly as you type.
- **Lung-Protective Targets**: Computes Predicted Body Weight (PBW) and relative Tidal Volume (Vt/PBW) to ensure adherence to protective ventilation strategies (≤ 6 mL/kg PBW).
- **ARDS Severity Stratification**: Evaluates oxygenation parameters (P/F or S/F ratio) to classify ARDS severity and respiratory system compliance (CRS).
- **Actionable Alerts**: Generates clear visual alerts for protective thresholds (Safe, Warning, Danger) and suggests action plans (e.g., prone positioning, NMBA, ECMO considerations).
- **Privacy-First & Offline-Capable**: Built as a single-file, zero-dependency HTML application. Absolutely **no patient data is persisted, stored, or transmitted**. The tool is fully functional offline directly at the bedside.

## Clinical Parameters Evaluated

- **Patient Metrics**: Height, Biological Sex, Actual Body Weight
- **Oxygenation**: FiO₂, PaO₂ (ABG gold standard), SpO₂ (non-invasive)
- **Ventilator Settings**: Respiratory Rate (RR), Tidal Volume (Vt), Plateau Pressure (Pplat), PEEP

## Usage

Simply open the `index.html` file in any modern web browser (desktop, tablet, or smartphone). No installation, application server, or internet connection is required.

## References

This decision support tool is grounded in established critical care literature and guidelines, including:
- Devine GJ et al. *Clin Pharmacokinet* 1974 (Predicted Body Weight)
- ARDS Definition Task Force (Berlin Definition). *JAMA* 2012
- Amato MB et al. *NEJM* 2015 (Driving Pressure)
- Gattinoni L et al. *ICM* 2016 (Mechanical Power)
- Rice TW et al. *Chest* 2007 / Brown SM et al. *Chest* 2016 (SpO₂/FiO₂ ratio)
- Guérin C et al. *NEJM* 2013 (PROSEVA Trial)
- Papazian L et al. *NEJM* 2010 (ACURASYS Trial)
- Combes A et al. *NEJM* 2018 (EOLIA Trial)

## Author

**Sacha Rozencwajg, MD**  
Anesthesiologist-Intensivist  
Hôpital Marie-Lannelongue / GH Paris Saint-Joseph  
INSERM U1358 — Université Paris-Saclay  

---

**Disclaimer:** This software is a clinical decision support tool and **does not replace expert clinical judgment**. Always evaluate patients individually according to local protocols.
