# Schematron (Geschäftsregeln, die das XSD nicht prüft)

Ausgeführt über `saxonche` (Saxon-HE, XSLT 2.0) in
`zugferd.validate_schematron()`. Das XRechnung-Profil wird automatisch an der
Spec-ID im XML erkannt; dann laufen zusätzlich die BR-DE-Regeln.

## `EN16931-CII-validation.xslt`
EN-16931-Kernregeln (BR-*) für CII – fängt z. B. BR-O-02 / BR-O-05.
- Quelle: https://github.com/ConnectingEurope/eInvoicing-EN16931
  (`cii/xslt/EN16931-CII-validation.xslt`)
- Lizenz: EUPL v1.2

      curl -sSL -o EN16931-CII-validation.xslt \
        https://raw.githubusercontent.com/ConnectingEurope/eInvoicing-EN16931/master/cii/xslt/EN16931-CII-validation.xslt

## `XRechnung-CII-validation.xsl`
Zusätzliche XRechnung-BR-DE-Regeln (CIUS) für CII.
- Quelle: itplr-kosit/validator-configuration-xrechnung (Release-ZIP),
  Pfad `resources/xrechnung/<ver>/xsl/XRechnung-CII-validation.xsl`
- Stand: XRechnung 3.0.2 (Release v2026-01-31)
- Lizenz: Apache-2.0
