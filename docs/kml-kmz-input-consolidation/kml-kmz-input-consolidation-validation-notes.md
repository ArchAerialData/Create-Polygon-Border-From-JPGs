# KML/KMZ Input Consolidation Validation Notes

Status: automated validation passed; required North 2 real-sample validation blocked because the source paths are not accessible in this environment.

Date: 2026-07-01

## Commands Run

```powershell
git status --short --branch
git check-ignore -v test_data/
python -B -m unittest discover -s tests
python -B -c "from pathlib import Path; files=list(Path('src').rglob('*.py')); [compile(path.read_text(encoding='utf-8'), str(path), 'exec') for path in files]; print(f'compiled {len(files)} source files')"
python -B -c "import sys; from pathlib import Path; sys.path.insert(0, str(Path('src').resolve())); from jpg_boundary_kmz_gui import _create_root, BoundaryKmzApp; root=_create_root(); root.withdraw(); app=BoundaryKmzApp(root); root.update_idletasks(); root.destroy(); print('GUI smoke ok')"
git diff --name-only
```

Results:

- `git check-ignore -v test_data/`: passed; `.gitignore:2:test_data/ test_data/`.
- `python -B -m unittest discover -s tests`: passed; 50 tests.
- source compile command: passed; 9 source files.
- GUI smoke command: passed; `GUI smoke ok`.

## Disposable Synthetic Validation

Input:

- Temporary KML with one `LineString`.
- Buffer: `170 ft`.
- Sections: `2`.
- Overlap: `25 ft`.
- Split direction: `90 deg`.
- Output: disposable temp KMZ, not committed.

Observed result:

- Input type: `KML polyline`.
- Sections generated: `2`.
- Final projected polygon interiors: `0`.
- Selected split direction: `90.0 deg`.
- Section area variance: `0.000%`.
- KMZ file was created in the temporary directory.

## Required North 2 Real-Sample Validation

Required source KML:

```text
A:\z_TemporaryDailes_z\Motiva Mapping\_Crops\Day 4 - Test\Northern Section\North 2\photo_polylines_20260630_162709.kml
```

Required reference KML:

```text
A:\z_TemporaryDailes_z\Motiva Mapping\_Crops\Day 4 - Test\Northern Section\North 2\photo_polylines_20260630_162709_170ft_buffer.kml
```

Access check:

```powershell
Test-Path -LiteralPath '<source KML>'
Test-Path -LiteralPath '<reference KML>'
```

Result:

- Source KML: `False`.
- Reference KML: `False`.

Because both required files are inaccessible, the North 2 exterior-boundary comparison and visual crop-shape validation could not be completed in this environment.

## Safety Confirmation

- No Metashape process, project artifact, task queue, or processing job was launched, inspected, modified, interrupted, or otherwise touched.
- `test_data/` was not modified.
- `outputs/` was not modified by validation.
- The `A:\...` source sample folder was not modified.
- Buffer-Zone-Generator was not modified.

## Residual Risk

- Real-sample validation against the North 2 source KML and 170 ft reference KML remains required once those paths are available.
