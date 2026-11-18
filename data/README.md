# Dataset and methodology

## Source and license

This project uses the **I-BLEND** campus building-energy dataset published by researchers at IIIT-Delhi. The source paper describes one-minute electricity measurements for seven building groups and provides a separate institute calendar. The source dataset is published under **CC0 1.0** in Figshare. This repository includes a small derived hourly CSV, with source attribution retained here.

- Dataset article: [Rashid et al., Scientific Data 6, 190015 (2019)](https://www.nature.com/articles/sdata201915).
- Energy archive and version metadata: [Figshare DOI 10.6084/m9.figshare.6007637.v1](https://doi.org/10.6084/m9.figshare.6007637.v1); [archive download](https://ndownloader.figshare.com/files/10797959).
- Academic calendar archive: [Figshare DOI 10.6084/m9.figshare.6007634.v1](https://doi.org/10.6084/m9.figshare.6007634.v1); [archive download](https://ndownloader.figshare.com/files/10797956).

The original energy archive is about 562 MB. The project includes only `energy_hourly.csv.gz` (about 2.1 MB), `buildings.csv`, and the generated profile so that the dashboard can build quickly and the source data need not be re-downloaded.

## Included files

- `energy_hourly.csv.gz`: 269,640 hourly building records for 7 building groups, from 2013-08-10 through 2017-12-31, local time.
- `buildings.csv`: building labels, types, reported floor area converted to square metres, and floor count from the paper's building descriptions.
- `dataset_profile.json`: date range, counts, quality summary, and a reproduction command.

The source power columns are in watts. Separate mains and backup readings are added for each dormitory only when both values are present. `Mess` is represented as the dining building. `Facilities` remains its own group. The CSV does not contain names or personally identifying information.

## Processing choices

1. Read the source CSV inside its ZIP in chunks; convert Unix timestamps to `Asia/Kolkata` local time.
2. Aggregate each building's minute power values into an hourly mean in kW. For a one-hour interval, that mean corresponds to the hourly kWh estimate.
3. Calculate coverage as available minute samples divided by 60. Leave missing and unusable measurements empty rather than changing them to zero. Energy is included only when coverage is at least 75%; quality is marked complete at 95% or more, partial from 1% to less than 95%, and missing at 0%.
4. Join the published working-day and high/low activity calendar when a calendar record exists. Missing calendar context is labeled `Unknown`.
5. Flag an unusually high hourly power value for review only when there are at least 12 peer values for the same building, weekday, hour, and activity band, and the value exceeds both 2.5 times its peer median and a robust median-deviation threshold. This is a review cue, not an equipment fault label.

The output profile reports 225,650 complete hours, 2,861 partial hours, 41,129 missing hours, and 4,603 statistical spike flags. “Complete” follows the 95% coverage threshold. Some partial hours still have enough coverage to contribute to the energy sum; the dashboard reports usable-hour coverage separately.

## Carbon factor

The dashboard uses the CEA weighted-average grid factor for FY 2025–26, `0.675 tonnes CO₂/MWh`, numerically equivalent to `0.675 kg CO₂/kWh`. It applies that current published factor to the historic energy series as a scenario estimate so the displayed carbon number is consistent with the selected kWh. It does not represent the actual grid mix in 2013–2017, measured scope 2 emissions, or CO₂-equivalent greenhouse gases.

Source: [CEA CO₂ Baseline Database](https://cea.nic.in/cdm-co2-baseline-view?lang=en&mappingId=234), [User Guide v22.0 PDF](https://cea.nic.in/api/cdm-report-version/view-pdf/en/82), weighted-average factor for FY 2025–26.

## Reproduce from source archives

Install Python 3.10+ and pandas, place the downloaded archive files in a local working directory, and run from the project root:

```sh
python -m pip install pandas
python scripts/prepare_dataset.py --energy-archive energy_dataset.zip --calendar-archive iiitd_calender_schedule.zip
```

The script overwrites the derived data files in this folder. The source archives are excluded from Docker build context by `.dockerignore` and are not needed for normal startup.
