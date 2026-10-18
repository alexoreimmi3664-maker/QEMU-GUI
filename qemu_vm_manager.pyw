"""
QEMU VM Manager - simple GUI for creating and launching QEMU virtual machines.

Usage: copy this file into your QEMU folder (next to qemu-system-x86_64.exe
and qemu-img.exe) and double-click it. Requires Python 3 (python.org).

VMs are stored in a "vms" sub-folder: vms/<name>/vm.json, disk image, UEFI vars.
"""
import os
import sys
import json
import shutil
import shlex
import subprocess
import glob
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

BASE = os.path.dirname(os.path.abspath(__file__))


def pick_vms_dir():
    """Use <qemu folder>\\vms if writable, else Documents\\QEMU VMs."""
    p = os.path.join(BASE, "vms")
    try:
        os.makedirs(p, exist_ok=True)
        t = os.path.join(p, ".write_test")
        with open(t, "w"):
            pass
        os.remove(t)
        return p
    except OSError:
        return os.path.join(os.path.expanduser("~"), "Documents", "QEMU VMs")


VMS_DIR = pick_vms_dir()
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

DEFAULTS = {
    "name": "New VM", "arch": "", "cpus": "2", "ram": "4096",
    "disk_gb": "40", "disk_path": "", "disk_if": "ide",
    "iso": "", "iso2": "", "boot": "CD-ROM first",
    "accel": "whpx", "cpu": "qemu64", "machine": "q35",
    "display": "gtk", "vga": "std", "net_model": "e1000", "hostfwd": "",
    "uefi": False, "sound": True, "tablet": True, "extra": "",
}
FMT = {".qcow2": "qcow2", ".vhdx": "vhdx", ".vmdk": "vmdk", ".vdi": "vdi",
       ".img": "raw", ".raw": "raw"}


def find_systems():
    out = []
    for p in glob.glob(os.path.join(BASE, "qemu-system-*.exe")):
        n = os.path.basename(p)
        if not n.lower().endswith("w.exe"):
            out.append(n)
    return sorted(out)


def qemu_img():
    p = os.path.join(BASE, "qemu-img.exe")
    return p if os.path.exists(p) else shutil.which("qemu-img")


def esc(path):
    """Escape commas for -drive file= arguments."""
    return path.replace(",", ",,")


def disk_fmt(path):
    return FMT.get(os.path.splitext(path)[1].lower(), "qcow2")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("QEMU VM Manager")
        self.geometry("920x640")
        self.minsize(820, 560)
        self.systems = find_systems()
        self.v = {}
        self.current = None
        os.makedirs(VMS_DIR, exist_ok=True)
        self.build_ui()
        self.refresh_list()
        self.new_vm()
        if not self.systems:
            messagebox.showwarning(
                "QEMU not found",
                "No qemu-system-*.exe found in:\n%s\n\nPut this file in your QEMU "
                "install folder." % BASE)

    # ---------------------------------------------------------------- UI
    def build_ui(self):
        left = ttk.Frame(self, padding=8)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Virtual machines", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.lb = tk.Listbox(left, width=24, exportselection=False)
        self.lb.pack(fill="y", expand=True, pady=4)
        self.lb.bind("<<ListboxSelect>>", self.on_select)
        ttk.Button(left, text="+ New VM", command=self.new_vm).pack(fill="x", pady=2)
        ttk.Button(left, text="Delete VM", command=self.delete_vm).pack(fill="x", pady=2)
        ttk.Button(left, text="Open VMs folder",
                   command=lambda: os.startfile(VMS_DIR)).pack(fill="x", pady=2)

        right = ttk.Frame(self, padding=8)
        right.pack(side="left", fill="both", expand=True)
        nb = ttk.Notebook(right)
        nb.pack(fill="both", expand=True)
        tabs = {}
        for t in ("General", "Storage", "Hardware", "Network & Display", "Advanced"):
            f = ttk.Frame(nb, padding=12)
            f.columnconfigure(1, weight=1)
            nb.add(f, text=t)
            tabs[t] = f

        g = tabs["General"]
        self.field(g, 0, "VM name", "name")
        self.field(g, 1, "Architecture", "arch", "combo", self.systems, readonly=True)
        self.field(g, 2, "CPU cores", "cpus", "spin", (1, 64))
        self.field(g, 3, "RAM (MB)", "ram", "spin", (256, 262144, 256))
        self.field(g, 4, "Accelerator", "accel", "combo", ["whpx", "tcg"], readonly=True)
        ttk.Label(g, foreground="gray", wraplength=520, justify="left",
                  text="whpx = hardware acceleration (enable 'Windows Hypervisor Platform' in "
                       "Windows Features). tcg = slow software emulation, works everywhere."
                  ).grid(row=5, column=0, columnspan=3, sticky="w", pady=8)

        s = tabs["Storage"]
        self.field(s, 0, "Disk size (GB)", "disk_gb", "spin", (1, 4096))
        self.field(s, 1, "Disk image", "disk_path", "entry", browse="save")
        ttk.Label(s, foreground="gray", text="Leave empty to auto-create vms/<name>/disk.qcow2. "
                  "Pick an existing file to reuse it.").grid(row=2, column=0, columnspan=3, sticky="w")
        self.field(s, 3, "Disk interface", "disk_if", "combo", ["ide", "virtio", "nvme"], readonly=True)
        self.field(s, 4, "Install ISO", "iso", "entry", browse="open")
        self.field(s, 5, "Second ISO (drivers)", "iso2", "entry", browse="open")
        self.field(s, 6, "Boot order", "boot", "combo", ["CD-ROM first", "Disk first"], readonly=True)
        ttk.Label(s, foreground="gray", wraplength=520, justify="left",
                  text="Tip: 'virtio' is faster but Windows needs the virtio-win driver ISO "
                       "attached as second ISO. Use 'ide' for an easy first install."
                  ).grid(row=7, column=0, columnspan=3, sticky="w", pady=8)

        h = tabs["Hardware"]
        self.field(h, 0, "CPU model", "cpu", "combo", ["qemu64", "Skylake-Client", "EPYC", "max", "host"])
        self.field(h, 1, "Machine type", "machine", "combo", ["q35", "pc", "virt"])
        self.field(h, 2, "UEFI firmware", "uefi", "check", text="Boot with UEFI (OVMF)")
        self.field(h, 3, "Sound", "sound", "check", text="Intel HDA audio")
        self.field(h, 4, "Mouse", "tablet", "check", text="USB tablet (smooth mouse, no capture)")

        n = tabs["Network & Display"]
        self.field(n, 0, "Display", "display", "combo", ["gtk", "sdl", "vnc=:0"])
        self.field(n, 1, "Graphics card", "vga", "combo", ["std", "virtio", "qxl", "vmware", "cirrus"])
        self.field(n, 2, "Network card", "net_model", "combo", ["e1000", "virtio-net-pci", "rtl8139"])
        self.field(n, 3, "Port forwards", "hostfwd", "entry")
        ttk.Label(n, foreground="gray", wraplength=520, justify="left",
                  text="Format: tcp::2222-:22 (host port 2222 -> guest 22). Separate multiple "
                       "with commas, e.g. tcp::2222-:22,tcp::8080-:80"
                  ).grid(row=4, column=0, columnspan=3, sticky="w", pady=8)

        a = tabs["Advanced"]
        self.field(a, 0, "Extra QEMU args", "extra", "entry")
        ttk.Label(a, foreground="gray", text="Appended to the command line as-is.").grid(
            row=1, column=0, columnspan=3, sticky="w")

        bar = ttk.Frame(right)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="Save", command=self.save).pack(side="left", padx=2)
        ttk.Button(bar, text="Save && Start", command=self.start).pack(side="left", padx=2)
        ttk.Button(bar, text="Start (show errors)", command=lambda: self.start(debug=True)
                   ).pack(side="left", padx=2)
        ttk.Button(bar, text="Show command", command=self.show_cmd).pack(side="left", padx=2)
        ttk.Button(bar, text="Create start.bat", command=self.make_bat).pack(side="left", padx=2)
        self.status = ttk.Label(right, text="", foreground="gray")
        self.status.pack(anchor="w", pady=4)

    def field(self, parent, row, label, key, kind="entry", values=None, browse=None,
              readonly=False, text=""):
        if kind == "check":
            var = tk.BooleanVar(value=DEFAULTS[key])
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Checkbutton(parent, text=text, variable=var).grid(row=row, column=1, sticky="w")
        else:
            var = tk.StringVar(value=DEFAULTS[key])
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
            if kind == "combo":
                w = ttk.Combobox(parent, textvariable=var, values=values,
                                 state="readonly" if readonly else "normal")
            elif kind == "spin":
                w = ttk.Spinbox(parent, textvariable=var, from_=values[0], to=values[1],
                                increment=values[2] if len(values) > 2 else 1)
            else:
                w = ttk.Entry(parent, textvariable=var)
            w.grid(row=row, column=1, sticky="ew", pady=4)
            if browse:
                ttk.Button(parent, text="Browse...", command=lambda: self.pick(var, browse)
                           ).grid(row=row, column=2, padx=4)
        self.v[key] = var

    def pick(self, var, mode):
        if mode == "open":
            p = filedialog.askopenfilename(filetypes=[("Disc images", "*.iso"), ("All files", "*.*")])
        else:
            p = filedialog.asksaveasfilename(
                defaultextension=".qcow2", confirmoverwrite=False,
                filetypes=[("Disk images", "*.qcow2 *.img *.raw *.vhdx *.vmdk *.vdi"), ("All", "*.*")])
        if p:
            var.set(os.path.normpath(p))

    # ------------------------------------------------------------ VM store
    def vm_dir(self, name):
        return os.path.join(VMS_DIR, name)

    def refresh_list(self, select=None):
        self.lb.delete(0, "end")
        names = sorted(d for d in os.listdir(VMS_DIR)
                       if os.path.exists(os.path.join(VMS_DIR, d, "vm.json")))
        for n in names:
            self.lb.insert("end", n)
        if select in names:
            self.lb.selection_set(names.index(select))

    def get(self):
        return {k: (v.get() if isinstance(v, tk.BooleanVar) else v.get().strip())
                for k, v in self.v.items()}

    def set(self, data):
        for k, v in self.v.items():
            v.set(data.get(k, DEFAULTS[k]))

    def new_vm(self):
        self.current = None
        self.lb.selection_clear(0, "end")
        d = dict(DEFAULTS)
        pref = [s for s in self.systems if "x86_64" in s]
        d["arch"] = (pref or self.systems or [""])[0]
        self.set(d)

    def on_select(self, _e=None):
        sel = self.lb.curselection()
        if not sel:
            return
        name = self.lb.get(sel[0])
        try:
            with open(os.path.join(self.vm_dir(name), "vm.json"), encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return
        self.current = name
        self.set(data)

    def delete_vm(self):
        sel = self.lb.curselection()
        if not sel:
            return
        name = self.lb.get(sel[0])
        if messagebox.askyesno("Delete", "Delete '%s' INCLUDING its disk image in the vms folder?" % name):
            shutil.rmtree(self.vm_dir(name), ignore_errors=True)
            self.refresh_list()
            self.new_vm()

    def save(self, quiet=False):
        d = self.get()
        name = d["name"]
        bad = set('\\/:*?"<>|')
        if not name or any(c in bad for c in name):
            messagebox.showerror("Name", "Enter a valid VM name (no \\ / : * ? \" < > |).")
            return None
        if not d["arch"]:
            messagebox.showerror("QEMU", "No QEMU executable selected.")
            return None
        vdir = self.vm_dir(name)
        os.makedirs(vdir, exist_ok=True)
        if self.current and self.current != name and os.path.isdir(self.vm_dir(self.current)):
            if messagebox.askyesno("Rename", "Move '%s' to the new name '%s'?" % (self.current, name)):
                pass  # simple: keep old folder, new one is a copy of settings
        if not d["disk_path"]:
            d["disk_path"] = os.path.join(vdir, "disk.qcow2")
            self.v["disk_path"].set(d["disk_path"])
        if not os.path.exists(d["disk_path"]):
            img = qemu_img()
            if not img:
                messagebox.showerror("qemu-img", "qemu-img.exe not found.")
                return None
            os.makedirs(os.path.dirname(d["disk_path"]), exist_ok=True)
            r = subprocess.run([img, "create", "-f", disk_fmt(d["disk_path"]), d["disk_path"],
                                "%sG" % d["disk_gb"]], capture_output=True, text=True,
                               creationflags=NOWIN)
            if r.returncode != 0:
                messagebox.showerror("Disk creation failed", r.stderr or r.stdout)
                return None
        with open(os.path.join(vdir, "vm.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        self.current = name
        self.refresh_list(select=name)
        self.status.config(text="Saved '%s'." % name)
        return d

    # ------------------------------------------------------------- command
    def build_cmd(self, d):
        exe = os.path.join(BASE, d["arch"])
        c = [exe, "-name", d["name"], "-machine", d["machine"]]
        if d["accel"] == "whpx":
            c += ["-accel", "whpx,kernel-irqchip=off"]
        else:
            c += ["-accel", "tcg,thread=multi"]
        cpu = d["cpu"]
        if d["accel"] == "whpx" and cpu in ("max", "host", ""):
            cpu = "qemu64"  # 'max'/'host' crash WHPX on CPUs with APX/MPX
        if cpu:
            c += ["-cpu", cpu]
        c += ["-smp", d["cpus"], "-m", d["ram"]]

        if d["uefi"] and "x86_64" in d["arch"]:
            code = os.path.join(BASE, "share", "edk2-x86_64-code.fd")
            vars_src = os.path.join(BASE, "share", "edk2-i386-vars.fd")
            vars_dst = os.path.join(self.vm_dir(d["name"]), "vars.fd")
            if os.path.exists(code) and os.path.exists(vars_src):
                if not os.path.exists(vars_dst):
                    shutil.copy(vars_src, vars_dst)
                c += ["-drive", "if=pflash,format=raw,readonly=on,file=" + esc(code),
                      "-drive", "if=pflash,format=raw,file=" + esc(vars_dst)]
            else:
                self.status.config(text="UEFI files not found in share\\ - booting BIOS instead.")

        if d["disk_path"]:
            c += ["-drive", "file=%s,if=%s,format=%s,index=0" %
                  (esc(d["disk_path"]), d["disk_if"] if d["disk_if"] != "nvme" else "none",
                   disk_fmt(d["disk_path"]))]
            if d["disk_if"] == "nvme":
                c[-1] = "file=%s,if=none,id=nvm0,format=%s" % (esc(d["disk_path"]), disk_fmt(d["disk_path"]))
                c += ["-device", "nvme,drive=nvm0,serial=qemu0001"]
        if d["iso"]:
            c += ["-drive", "file=%s,media=cdrom,readonly=on,index=2" % esc(d["iso"])]
        if d["iso2"]:
            c += ["-drive", "file=%s,media=cdrom,readonly=on,index=3" % esc(d["iso2"])]
        c += ["-boot", "order=%s,menu=on" % ("d" if d["boot"].startswith("CD") else "c")]

        net = "user,id=n0"
        for fw in [x.strip() for x in d["hostfwd"].split(",") if x.strip()]:
            net += ",hostfwd=" + fw
        c += ["-netdev", net, "-device", "%s,netdev=n0" % d["net_model"]]

        c += ["-display", d["display"]]
        if d["vga"]:
            c += ["-vga", d["vga"]]
        if d["sound"]:
            c += ["-device", "intel-hda", "-device", "hda-duplex"]
        if d["tablet"]:
            c += ["-device", "qemu-xhci", "-device", "usb-tablet"]
        if d["extra"]:
            c += shlex.split(d["extra"], posix=False)
        return c

    def start(self, debug=False):
        d = self.save()
        if not d:
            return
        cmd = self.build_cmd(d)
        if not os.path.exists(cmd[0]):
            messagebox.showerror("QEMU", "Not found: " + cmd[0])
            return
        try:
            if debug:
                # console stays open after QEMU exits so the error can be read
                line = subprocess.list2cmdline(cmd)
                subprocess.Popen('cmd /k "%s"' % line, cwd=BASE,
                                 creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                subprocess.Popen(cmd, cwd=BASE)
            self.status.config(text="Started '%s'." % d["name"])
        except Exception as e:
            messagebox.showerror("Launch failed", str(e))

    def show_cmd(self):
        d = self.get()
        if not d["arch"]:
            return
        text = subprocess.list2cmdline(self.build_cmd(d))
        w = tk.Toplevel(self)
        w.title("QEMU command")
        t = tk.Text(w, width=100, height=10, wrap="word")
        t.insert("1.0", text)
        t.pack(fill="both", expand=True, padx=8, pady=8)
        def cp():
            self.clipboard_clear()
            self.clipboard_append(text)
        ttk.Button(w, text="Copy", command=cp).pack(pady=(0, 8))

    def make_bat(self):
        d = self.save()
        if not d:
            return
        path = os.path.join(self.vm_dir(d["name"]), "start.bat")
        with open(path, "w", encoding="utf-8") as f:
            f.write("@echo off\r\ncd /d \"%s\"\r\n%s\r\n" %
                    (BASE, subprocess.list2cmdline(self.build_cmd(d))))
        messagebox.showinfo("Created", "Saved:\n" + path)


if __name__ == "__main__":
    App().mainloop()
