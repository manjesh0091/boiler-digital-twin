# Modular Boiler Efficiency Calculation (Python)

This codebase implements the calculation as independent modules:

- M01 boiler duty
- M02 fuel basis conversion and blending
- M03 Dulong GCV validation/correction
- M04 refuse, theoretical air, excess air and dry-gas composition
- M05 psychrometrics
- M06 wet/dry air and flue-gas rates plus air-heater leakage
- M07 fuel firing and total air flow
- M08 ASME-style energy-balance heat losses and credits
- M09 Appendix D-4 contract/design corrections

## Run the included Appendix D-4 example

```bash
python run_example.py
```

The results are written to `examples/mundra_result.json`.

## Run tests

```bash
python -m pytest -q
```

## Important engineering controls

1. All fuel constituents are mass percent on an as-fired basis unless explicitly stated.
2. O2 is dry volume percent at the stated measurement location.
3. Pressure is absolute.
4. Heat losses and credits are percentages of HHV input.
5. Enthalpy inputs must be produced by an approved property/correlation library with a common reference state.
6. The G-factor correction is disabled by default because its direction requires engineering approval.
7. The password-protected ASME PDF was not machine-readable; implementation is based on the accessible Appendix D-4, the supplied write-ups and TEST_REP formulas. Verify against the licensed governing standard before contractual use.
