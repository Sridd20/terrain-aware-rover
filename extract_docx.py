
import zipfile
import xml.etree.ElementTree as ET
import sys

sys.stdout.reconfigure(encoding='utf-8')

docx_path = r'c:\Users\sridh\OneDrive\Documents\terrain-aware\documents\Terrain_Rover_Developer_Doc.docx'
output_path = r'c:\Users\sridh\OneDrive\Documents\terrain-aware\documents\extracted_doc.txt'

z = zipfile.ZipFile(docx_path)
tree = ET.parse(z.open('word/document.xml'))
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

lines = []
for p in tree.findall('.//w:p', ns):
    text = ''.join(node.text or '' for node in p.findall('.//w:t', ns))
    lines.append(text)

full_text = '\n'.join(lines)

with open(output_path, 'w', encoding='utf-8') as f:
    f.write(full_text)

print(f"Extracted {len(lines)} lines to {output_path}")
