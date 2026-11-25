from pathlib import Path
import tempfile
import unittest
import zipfile
from soccer_recorder.xlsx_schedule import XlsxScheduleReader, google_sheet_export_url

class ScheduleReaderTests(unittest.TestCase):
    def test_reads_only_green_rows(self):
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        rows = [["Date", "Home Team", "Away Team", "Kick Off Time", "Livestream Link"],
                ["2026-11-25", "Home A", "Away A", "17:00", "https://example.com/game1"],
                ["2026-11-25", "Home B", "Away B", "19:00", "https://example.com/game2"]]
        xml = f'<worksheet xmlns="{ns}"><sheetData>'
        for i, row in enumerate(rows, 1):
            xml += f'<row r="{i}">'
            for j, val in enumerate(row):
                xml += f'<c r="{chr(65+j)}{i}" t="inlineStr" s="{1 if i==2 else 0}"><is><t>{val}</t></is></c>'
            xml += '</row>'
        xml += '</sheetData></worksheet>'
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"fixture.xlsx"
            with zipfile.ZipFile(p, 'w') as z:
                z.writestr('xl/worksheets/sheet1.xml', xml)
                z.writestr('xl/styles.xml', f'<styleSheet xmlns="{ns}"><fills><fill><patternFill/></fill><fill><patternFill><fgColor rgb="FF00FF00"/></patternFill></fill></fills><cellXfs><xf fillId="0"/><xf fillId="1"/></cellXfs></styleSheet>')
                z.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Schedule" sheetId="1" r:id="rId1"/></sheets></workbook>')
                z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
            reader = XlsxScheduleReader(p)
            games = reader.read_games(selected_only=True)
            self.assertEqual(len(games), 1)
            self.assertEqual(games[0].home_team, 'Home A')
            self.assertEqual(games[0].kickoff.hour, 17)
            self.assertEqual(len(reader.read_games(selected_only=False)), 2)

    def test_google_sheet_export(self):
        self.assertEqual(google_sheet_export_url('https://docs.google.com/spreadsheets/d/test_ID/edit#gid=456'), 'https://docs.google.com/spreadsheets/d/test_ID/export?format=xlsx&gid=456')
