# MiniCut — โครงสร้างโค้ดแบบแยกส่วน

เปิดโปรแกรมเหมือนเดิม: ดับเบิลคลิก `Run_MiniCut.bat` (หรือ `python file.py`)
โฟลเดอร์ `svg/` ต้องอยู่ข้างๆ `file.py` เหมือนเดิม และ **ไม่ต้องใช้ `capcut_patch.py` อีกแล้ว (ลบทิ้งได้)** เพราะทุกอย่างในนั้นถูกรวมเป็นโค้ดจริงแล้ว

## แผนที่โค้ด — อยากแก้อะไร ไปที่ไหน

| ส่วน | ไฟล์ | มีอะไร |
|---|---|---|
| **สร้าง Project** | `minicut/project/create.py` | หน้าแรก, กล่องสร้างโปรเจกต์ใหม่, เปิด/บันทึกไฟล์ `.minicut`, รายการโปรเจกต์ล่าสุด |
| **Workspace ตัดต่อ** | `minicut/workspace/viewport.py` | Viewport: พรีวิว, กรอบเลือก/ย่อขยาย/หมุน, box selection, มิเตอร์เสียง |
| | `minicut/workspace/timeline.py` | ไทม์ไลน์: แทร็ก, คลิป, keyframe, box selection, snap, เมนูคลิกขวา, แถบเครื่องมือ |
| | `minicut/workspace/panels.py` | แผงซ้าย/ขวา: Media, ปุ่มพรีวิว, Inspector (Properties), แท็บ Mask |
| | `minicut/workspace/node_editor.py` | หน้า Node (canvas 2D) |
| | `minicut/workspace/actions.py` | คำสั่งตัดต่อ: undo/redo, เลือก, เพิ่ม/ตัด/ลบ/Group/Compound/Trim, วางเลย์เอาต์ Workspace |
| **Render** | `minicut/render/renderer.py` | วาดเฟรม (ซ้อนเลเยอร์, Mask, ข้อความ, Compound) + ตัวเรนเดอร์พรีวิวหลัง thread |
| | `minicut/render/media.py` | ตัวอ่านวิดีโอ/รูป/GIF, MediaPool, แคชเสียง, thumbnail |
| | `minicut/render/audio.py` | ผสมเสียง, เล่นเสียงแบบ streaming, ค่ามิเตอร์ |
| | `minicut/render/nodegraph.py` | ตัวคำนวณ Node (ไม่แก้ค่าเดิมของคลิป) |
| | `minicut/render/preview.py` | เล่น/seek/นาฬิกา และการขอเรนเดอร์พรีวิว |
| | `minicut/render/export.py` | หน้าต่าง Export และตัว Export เบื้องหลัง |
| **ส่วนกลาง** | `minicut/shared/core.py` | ค่าคงที่, ข้อมูลโปรเจกต์ (`Project`), Settings, keyframe/property |
| | `minicut/shared/theme.py`, `appearance.py` | ค่าสี/ขนาดทั้งหมด + stylesheet, การ apply แบบสด |
| | `minicut/shared/widgets.py` | วิดเจ็ตทั่วไป: ตัวเลือกสี, กราฟ ease/curve, Panel, Toast |
| | `minicut/shared/dialogs.py` | หน้าต่าง Settings และ Shortcuts |
| | `minicut/shared/icons.py` | ไอคอน SVG จากโฟลเดอร์ `svg/` |
| **ประกอบรวม** | `minicut/app.py` | `MainWindow` (ประกอบ 4 ส่วนด้านบนเข้าด้วยกัน) และ `main()` |

หลักการ (ตรวจจากการ import จริงแล้ว): `render/` ไม่อ้างถึงโค้ดหน้าจอตัดต่อหรือการสร้างโปรเจกต์เลย, `project/` ไม่อ้างถึง `workspace/`, และ `workspace/` เรียกใช้ `render/` เพียงไม่กี่จุด (Renderer, ค่ามิเตอร์เสียง, ตัวคำนวณ Node)
จึงแก้ส่วนใดส่วนหนึ่งได้โดยไม่ต้องไล่อ่านทั้งก้อน ตัวอย่าง: อยากเพิ่ม Mask รูปใหม่ → แก้ `render/renderer.py` ที่เดียว, อยากเปลี่ยนหน้าตาไทม์ไลน์ → `workspace/timeline.py`

## สิ่งที่แก้ระหว่างย้ายโค้ด
- ชื่อ `PRESETS` ซ้ำกันสองที่ (ชุดสีของตัวเลือกสี กับชุดขนาดวิดีโอ) ทำให้ตัวเลือกสีใช้ข้อมูลผิดชุด → แยกเป็น `COLOR_PRESETS` และ `SIZE_PRESETS`
- ตัวเลือกสีแบบ popover เรียก `QPoint` ที่ไม่เคย import → แก้แล้ว
- เปิดโปรเจกต์ครั้งที่สองแล้ว error "already deleted" → แก้แล้ว (ไม่มีแถบเครื่องมือเก่าค้างจาก patch)
