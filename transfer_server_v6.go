// transfer_server_v6.go
package main

import (
	"archive/zip"
	"bufio"
	"bytes"
	"context"
	_ "embed" // go:embed
	"encoding/json"
	"errors"
	"fmt"
	"github.com/getlantern/systray"
	"github.com/kbinani/screenshot"
	"golang.org/x/image/draw"
	"image"
	"image/jpeg"
	"image/png"
	"io"
	"io/fs"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"time"
)

// ──────────────────────────── CONFIG ────────────────────────────

type AnnounceCfg struct {
	McastGroup     string   `json:"mcast_group"`
	McastPort      int      `json:"mcast_port"`
	IntervalSecond int      `json:"interval_seconds"`
	TargetSubnets  []string `json:"target_subnets"`
	TargetUnicast  []string `json:"target_unicast"`
}

type ServerCfg struct {
	Name     string      `json:"name"`
	TCPPort  int         `json:"tcpPort"`
	HTTPPort int         `json:"httpPort"`
	Key      string      `json:"key"`
	Announce AnnounceCfg `json:"announce"`
}

var cfg ServerCfg

func shotHandler(w http.ResponseWriter, r *http.Request) {
	// auth middleware kullanıyorsan burada key kontrolü YAPMA.
	// (auth(shotHandler) ile kayıt edeceğiz.)

	// 1 sn rate-limit
	now := time.Now().Unix()
	if now-atomic.LoadInt64(&lastShotUnix) < 1 {
		time.Sleep(200 * time.Millisecond)
	}
	atomic.StoreInt64(&lastShotUnix, time.Now().Unix())

	// parametreler
	q := 45
	if v := r.URL.Query().Get("q"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 1 && n <= 95 {
			q = n
		}
	}
	wpx := 260
	if v := r.URL.Query().Get("w"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 40 && n <= 1280 {
			wpx = n
		}
	}
	fmtStr := r.URL.Query().Get("fmt") // "jpg" | "png"
	if fmtStr == "" {
		fmtStr = "jpg"
	}

	displays, err := parseDisplayParam(r.URL.Query().Get("display"))
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	img, err := captureScreens(displays)
	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	img = resizeToWidth(img, wpx)

	w.Header().Set("Cache-Control", "no-store")
	switch fmtStr {
	case "png":
		w.Header().Set("Content-Type", "image/png")
		_ = png.Encode(w, img)
	default:
		w.Header().Set("Content-Type", "image/jpeg")
		_ = jpeg.Encode(w, img, &jpeg.Options{Quality: q})
	}
}

// --- screenshot helpers (TEK KOPYA OLSUN) ---
var lastShotUnix int64 // basit rate-limit

func parseDisplayParam(raw string) ([]int, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil, nil
	}
	parts := strings.Split(raw, ",")
	indexes := make([]int, 0, len(parts))
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		idx, err := strconv.Atoi(part)
		if err != nil {
			return nil, fmt.Errorf("invalid display index %q", part)
		}
		indexes = append(indexes, idx)
	}
	if len(indexes) == 0 {
		return nil, fmt.Errorf("no display index provided")
	}
	return indexes, nil
}

func captureScreens(indexes []int) (image.Image, error) {
	total := screenshot.NumActiveDisplays()
	if total <= 0 {
		return nil, fmt.Errorf("no active display")
	}

	if len(indexes) == 0 {
		indexes = make([]int, total)
		for i := range indexes {
			indexes[i] = i
		}
	} else {
		uniq := indexes[:0]
		seen := make(map[int]struct{}, len(indexes))
		for _, idx := range indexes {
			if idx < 0 || idx >= total {
				return nil, fmt.Errorf("display index %d out of range (0-%d)", idx, total-1)
			}
			if _, ok := seen[idx]; ok {
				continue
			}
			seen[idx] = struct{}{}
			uniq = append(uniq, idx)
		}
		indexes = uniq
	}

	union := image.Rect(0, 0, 0, 0)
	bounds := make([]image.Rectangle, 0, len(indexes))
	for _, idx := range indexes {
		b := screenshot.GetDisplayBounds(idx)
		bounds = append(bounds, b)
		union = union.Union(b)
	}

	dst := image.NewRGBA(union)
	for i, idx := range indexes {
		b := bounds[i]
		img, err := screenshot.CaptureRect(b)
		if err != nil {
			return nil, err
		}
		draw.Draw(dst, b, img, image.Point{}, draw.Src)
	}

	return dst, nil
}

func resizeToWidth(src image.Image, w int) image.Image {
	if w <= 0 {
		return src
	}
	b := src.Bounds()
	sw, sh := b.Dx(), b.Dy()
	if sw <= w {
		return src
	}
	h := int(float64(sh) * float64(w) / float64(sw))
	dst := image.NewRGBA(image.Rect(0, 0, w, h))
	draw.ApproxBiLinear.Scale(dst, dst.Bounds(), src, b, draw.Over, nil)
	return dst
}

// ──────────────────────── güvenli silm ───────────────────────
// --- Silme güvenliği yardımcıları ---

// Windows kök sürücü mü? ("C:\" gibi)

// p, exeDir'in kendisi veya üzerinde mi?
func isInsideOrSame(p, exeDir string) bool {
	p = filepath.Clean(p)
	exeDir = filepath.Clean(exeDir)
	if p == exeDir {
		return true
	}
	rel, err := filepath.Rel(exeDir, p)
	if err != nil {
		return false
	}
	// exeDir altı değilse rel ".." ile başlar
	return !strings.HasPrefix(rel, "..")
}

// Silinmesi güvenli mi?
func safeToDelete(p string) bool {
	// 1) Boş veya var olmayan yol
	if p == "" {
		return false
	}
	// 2) Drive köklerini asla silme
	if isDriveRoot(p) {
		return false
	}
	// 3) Sunucunun çalıştığı klasörü ve altını koru
	exe, _ := os.Executable()
	exeDir := filepath.Dir(exe)
	if isInsideOrSame(p, exeDir) {
		return false
	}
	return true
}

func isDriveRoot(p string) bool {
	ap := filepath.Clean(p)
	if len(ap) == 3 && ap[1] == ':' && (ap[2] == '\\' || ap[2] == '/') {
		return true
	}
	return false
}

func clearReadonlyRecursive(p string) {
	_ = filepath.WalkDir(p, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		// Windows'ta read-only bayrağına denk gelen izinleri temizlemeye çalış
		if d.IsDir() {
			_ = os.Chmod(path, 0777)
		} else {
			_ = os.Chmod(path, 0666)
		}
		return nil
	})
}

func safeRemoveAll(p string) error {
	// Önce readonly/izinleri gevşet
	clearReadonlyRecursive(p)

	if err := os.RemoveAll(p); err == nil {
		return nil
	} else if runtime.GOOS == "windows" {
		fi, statErr := os.Stat(p)
		if statErr != nil {
			return err
		}
		if fi.IsDir() {
			// Windows'un yerel rmdir’i ile dene
			cmd := exec.Command("cmd", "/C", "rmdir", "/S", "/Q", p)
			return cmd.Run()
		} else {
			cmd := exec.Command("cmd", "/C", "del", "/F", "/Q", p)
			return cmd.Run()
		}
	} else {
		return err
	}
}

// ──────────────────────── GLOBALS / EMBED ───────────────────────

//go:embed tray.ico
var trayIcon []byte

var (
	httpServer     *http.Server
	tcpListener    net.Listener
	announceStopCh chan struct{}
	logFile        *os.File
)

// ───────────────────────────── MAIN ─────────────────────────────

func main() {
	setupLogging()
	loadConfig()
	systray.Run(onReady, onExit)
}

// ─────────────────────────── LOGGING ────────────────────────────

func setupLogging() {
	exe, _ := os.Executable()
	logPath := filepath.Join(filepath.Dir(exe), "server.log")
	f, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err == nil {
		log.SetOutput(f)
		logFile = f
	}
	log.SetFlags(log.LstdFlags | log.Lshortfile)
}

// ─────────────────────────── CONFIG IO ──────────────────────────

func loadConfig() {
	if f, err := os.Open("server_config.json"); err == nil {
		_ = json.NewDecoder(f).Decode(&cfg)
		_ = f.Close()
	}
	if cfg.Key == "" {
		cfg.Key = "1234"
	}
	if cfg.TCPPort == 0 {
		cfg.TCPPort = 5050
	}
	if cfg.HTTPPort == 0 {
		cfg.HTTPPort = 8088
	}
	if cfg.Announce.IntervalSecond == 0 {
		cfg.Announce.IntervalSecond = 5
	}
	if cfg.Announce.McastGroup == "" {
		cfg.Announce.McastGroup = "239.0.0.250"
	}
	if cfg.Announce.McastPort == 0 {
		cfg.Announce.McastPort = 9999
	}
	if cfg.Name == "" {
		if h, _ := os.Hostname(); h != "" {
			cfg.Name = h
		} else {
			cfg.Name = "Unnamed-PC"
		}
	}
}

// ─────────────────────────── CONFIG SAVE ───────────────────────────

// server_config.json dosyasını güvenli bir şekilde günceller.
// server_config.json dosyasını güvenli şekilde yazar.
func saveConfig(c ServerCfg) error {
	exe, _ := os.Executable()
	dir := filepath.Dir(exe)
	path := filepath.Join(dir, "server_config.json")
	tmp := filepath.Join(dir, "server_config_tmp.json")

	f, err := os.Create(tmp)
	if err != nil {
		return err
	}
	enc := json.NewEncoder(f)
	enc.SetIndent("", "  ")
	if err := enc.Encode(c); err != nil {
		f.Close()
		return err
	}
	f.Close()

	_ = os.Remove(path)
	if err := os.Rename(tmp, path); err != nil {
		return err
	}
	log.Println("✅ Config kaydedildi:", path)
	return nil
}

// GUI/HTTP ile server yapılandırmasını değiştirme endpoint'i
// GUI/HTTP ile server yapılandırmasını değiştirme endpoint'i
func updateConfigHandler(w http.ResponseWriter, r *http.Request) {
	key := r.URL.Query().Get("key")
	if key != cfg.Key {
		http.Error(w, "Yetkisiz", http.StatusForbidden)
		return
	}

	newName := r.URL.Query().Get("name")
	newTCP := r.URL.Query().Get("tcp")
	newHTTP := r.URL.Query().Get("http")
	newKey := r.URL.Query().Get("newkey")
	addUnicast := r.URL.Query().Get("add_unicast")

	changed := false

	if newName != "" && newName != cfg.Name {
		cfg.Name = newName
		changed = true
	}
	if newTCP != "" {
		if p, err := strconv.Atoi(newTCP); err == nil && p > 0 {
			cfg.TCPPort = p
			changed = true
		}
	}
	if newHTTP != "" {
		if p, err := strconv.Atoi(newHTTP); err == nil && p > 0 {
			cfg.HTTPPort = p
			changed = true
		}
	}
	if newKey != "" && newKey != cfg.Key {
		cfg.Key = newKey
		changed = true
	}

	// add_unicast gelmişse tek IP olarak ayarla
	if addUnicast != "" {
		cfg.Announce.TargetUnicast = []string{addUnicast}
		changed = true
		log.Println("🔄 TargetUnicast güncellendi:", addUnicast)
	}

	if changed {
		if err := saveConfig(cfg); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		log.Println("✅ Config güncellendi:", cfg)

		applyConfigChanged() // varsa port/announce yeniden başlatma vb.

		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("OK"))
		return
	} else {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("No changes"))
	}
}

func pingHandler(w http.ResponseWriter, r *http.Request) {
	jsonOut(w, map[string]any{
		"ok":            true,
		"name":          cfg.Name,
		"tcpPort":       cfg.TCPPort,
		"httpPort":      cfg.HTTPPort,
		"targetUnicast": cfg.Announce.TargetUnicast,
		"when":          time.Now().Format(time.RFC3339),
	})
}
func announceNowHandler(w http.ResponseWriter, r *http.Request) {
	// auth kontrolü mevcut auth() ile zaten sağlanacak
	go func() {
		// announceLoop içindeki payload ile aynı olsun
		msg := map[string]interface{}{
			"name":     cfg.Name,
			"ip":       getOutboundIP(),
			"tcpPort":  cfg.TCPPort,
			"httpPort": cfg.HTTPPort,
			"when":     time.Now().Format(time.RFC3339),
		}
		b, _ := json.Marshal(msg)

		// Multicast
		if cfg.Announce.McastGroup != "" && cfg.Announce.McastPort != 0 {
			addr := fmt.Sprintf("%s:%d", cfg.Announce.McastGroup, cfg.Announce.McastPort)
			if u, err := net.ResolveUDPAddr("udp4", addr); err == nil {
				if c, err := net.DialUDP("udp4", nil, u); err == nil {
					_, _ = c.Write(b)
					c.Close()
				}
			}
		}
		// Subnet broadcast
		for _, s := range cfg.Announce.TargetSubnets {
			for _, dst := range expandSubnetToBroadcast(s, cfg.Announce.McastPort) {
				if u, err := net.ResolveUDPAddr("udp4", dst); err == nil {
					if c, err := net.DialUDP("udp4", nil, u); err == nil {
						_, _ = c.Write(b)
						c.Close()
					}
				}
			}
		}
		// Unicast
		for _, ip := range cfg.Announce.TargetUnicast {
			dst := fmt.Sprintf("%s:%d", ip, cfg.Announce.McastPort)
			if u, err := net.ResolveUDPAddr("udp4", dst); err == nil {
				if c, err := net.DialUDP("udp4", nil, u); err == nil {
					_, _ = c.Write(b)
					c.Close()
				}
			}
		}
	}()
	_, _ = w.Write([]byte("OK"))
}

// ──────────────────────────── SYSTRAY ───────────────────────────

func onReady() {
	if len(trayIcon) > 0 {
		systray.SetIcon(trayIcon)
	}
	systray.SetTitle("DT Server")
	systray.SetTooltip(fmt.Sprintf("%s (TCP %d, HTTP %d)", cfg.Name, cfg.TCPPort, cfg.HTTPPort))

	mOpenFolder := systray.AddMenuItem("Klasörü Aç", "Program klasörünü aç")
	mOpenHTTP := systray.AddMenuItem("HTTP'yi Aç", "Sunucu HTTP ana sayfasını aç")
	mCopyIP := systray.AddMenuItem("IP Kopyala", "Bu makinenin IP adresini kopyala")
	systray.AddSeparator()
	mAnnPause := systray.AddMenuItemCheckbox("Duyuruyu Duraklat", "UDP announce duraklat/devam", false)
	mQuit := systray.AddMenuItem("Çıkış", "Sunucudan çık")

	startHTTP()
	startTCP()
	startAnnounce()

	go func() {
		for {
			select {
			case <-mOpenFolder.ClickedCh:
				openFolder()
			case <-mOpenHTTP.ClickedCh:
				openURL(fmt.Sprintf("http://127.0.0.1:%d", cfg.HTTPPort))
			case <-mCopyIP.ClickedCh:
				_ = setClipboard(getOutboundIP())
			case <-mAnnPause.ClickedCh:
				if mAnnPause.Checked() {
					mAnnPause.Uncheck()
					startAnnounce()
				} else {
					mAnnPause.Check()
					stopAnnounce()
				}
			case <-mQuit.ClickedCh:
				systray.Quit()
				return
			}
		}
	}()
}

func onExit() {
	stopAnnounce()
	stopTCP()
	stopHTTP()
	if logFile != nil {
		_ = logFile.Close()
	}
}

// ─────────────────────────── HELPERS ────────────────────────────

func openFolder() {
	exe, _ := os.Executable()
	dir := filepath.Dir(exe)
	switch runtime.GOOS {
	case "windows":
		_ = exec.Command("explorer", dir).Start()
	case "darwin":
		_ = exec.Command("open", dir).Start()
	default:
		_ = exec.Command("xdg-open", dir).Start()
	}
}

func openURL(url string) {
	switch runtime.GOOS {
	case "windows":
		_ = exec.Command("rundll32", "url.dll,FileProtocolHandler", url).Start()
	case "darwin":
		_ = exec.Command("open", url).Start()
	default:
		_ = exec.Command("xdg-open", url).Start()
	}
}

func setClipboard(text string) error {
	switch runtime.GOOS {
	case "windows":
		cmd := exec.Command("cmd", "/C", "clip")
		in, _ := cmd.StdinPipe()
		if err := cmd.Start(); err != nil {
			return err
		}
		_, _ = io.WriteString(in, text)
		_ = in.Close()
		return cmd.Wait()
	case "darwin":
		cmd := exec.Command("pbcopy")
		cmd.Stdin = bytes.NewBufferString(text)
		return cmd.Run()
	default:
		cmd := exec.Command("xclip", "-selection", "clipboard")
		cmd.Stdin = bytes.NewBufferString(text)
		return cmd.Run()
	}
}

// ──────────────────────────── HTTP API ──────────────────────────

func startHTTP() {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/roots", auth(rootsHandler))
	mux.HandleFunc("/api/shortcuts", auth(shortcutsHandler))
	mux.HandleFunc("/api/list", auth(listHandler))
	mux.HandleFunc("/api/mkdir", auth(mkdirHandler))
	mux.HandleFunc("/api/delete", auth(deleteHandler))
	mux.HandleFunc("/api/download", auth(downloadHandler))
	mux.HandleFunc("/api/update", auth(updateHandler))
	mux.HandleFunc("/api/update_config", auth(updateConfigHandler)) // ✅ yeni endpoint
	mux.HandleFunc("/api/rename", auth(renameHandler))
	mux.HandleFunc("/api/move", auth(moveHandler))
	mux.HandleFunc("/api/copy", auth(copyHandler))
	mux.HandleFunc("/api/features", auth(featuresHandler))
	mux.HandleFunc("/api/ping", auth(pingHandler))
	mux.HandleFunc("/api/announce_now", auth(announceNowHandler))
	mux.HandleFunc("/api/shot", auth(shotHandler))

	httpServer = &http.Server{
		Addr:    fmt.Sprintf(":%d", cfg.HTTPPort),
		Handler: mux,
	}
	go func() {
		log.Println("HTTP listening on", httpServer.Addr)
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Println("HTTP error:", err)
		}
	}()
}

func stopHTTP() {
	if httpServer != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_ = httpServer.Shutdown(ctx)
	}
}

func auth(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("key") != cfg.Key {
			http.Error(w, "Yetkisiz", http.StatusForbidden)
			return
		}
		next.ServeHTTP(w, r)
	}
}

func jsonOut(w http.ResponseWriter, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(v)
}

func rootsHandler(w http.ResponseWriter, r *http.Request) {
	var roots []string
	for _, letter := range "ABCDEFGHIJKLMNOPQRSTUVWXYZ" {
		path := fmt.Sprintf("%c:\\", letter)
		if _, err := os.Stat(path); err == nil {
			roots = append(roots, path)
		}
	}
	jsonOut(w, roots)
}

func shortcutsHandler(w http.ResponseWriter, r *http.Request) {
	home, _ := os.UserHomeDir()
	shorts := map[string]string{
		"Masaüstü":     filepath.Join(home, "Desktop"),
		"Belgeler":     filepath.Join(home, "Documents"),
		"İndirilenler": filepath.Join(home, "Downloads"),
	}
	jsonOut(w, shorts)
}

func listHandler(w http.ResponseWriter, r *http.Request) {
	p := r.URL.Query().Get("abs")
	if p == "" {
		p = "C:\\"
	}
	ents, err := os.ReadDir(p)
	if err != nil {
		http.Error(w, fmt.Sprintf("Listeleme hatası: %v", err), http.StatusInternalServerError)
		return
	}
	var out []map[string]interface{}
	for _, e := range ents {
		fi, _ := e.Info()
		m := map[string]interface{}{
			"name":  e.Name(),
			"type":  "dir",
			"mtime": fi.ModTime().Format("2006-01-02 15:04"),
		}
		if !e.IsDir() {
			m["type"] = "file"
			m["size"] = fi.Size()
		}
		out = append(out, m)
	}
	jsonOut(w, out)
}

func downloadHandler(w http.ResponseWriter, r *http.Request) {
	p := r.URL.Query().Get("abs")
	if p == "" {
		http.Error(w, "Eksik parametre", http.StatusBadRequest)
		return
	}

	info, err := os.Stat(p)
	if err != nil {
		http.Error(w, err.Error(), http.StatusNotFound)
		return
	}

	if !info.IsDir() {
		// DOSYA: var olan davranış
		// Tarayıcı/istemci ismi düzgün görsün diye header ekleyelim
		w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=%q", filepath.Base(p)))
		http.ServeFile(w, r, p)
		return
	}

	// KLASÖR: ZIP olarak stream et
	zipName := filepath.Base(p) + ".zip"
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=%q", zipName))

	zw := zip.NewWriter(w)
	defer zw.Close()

	// Yürüyüş: p altındaki her dosyayı arşive ekle
	base := p
	filepath.WalkDir(base, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			// walk hatası olursa zip yazımını bozmayalım: sadece loglayıp geç
			log.Println("walk:", err)
			return nil
		}

		// ZIP içinde kök: base klasör ADI (GUI zipten çıkartınca doğru klasör adıyla oluşsun diye)
		rel, err := filepath.Rel(filepath.Dir(base), path)
		if err != nil {
			return nil
		}
		// Windows -> arşiv içi path her zaman "/" ister
		rel = strings.ReplaceAll(rel, "\\", "/")

		// Klasör girdisi
		if d.IsDir() {
			// zip'te klasör olarak belirtmek için sonda "/" olmalı
			if rel != "" && !strings.HasSuffix(rel, "/") {
				rel += "/"
			}
			_, err := zw.Create(rel)
			if err != nil {
				log.Println("zip create dir:", err)
			}
			return nil
		}

		// Dosya girdisi
		f, err := os.Open(path)
		if err != nil {
			log.Println("open:", err)
			return nil
		}
		defer f.Close()

		fi, _ := f.Stat()
		hdr, err := zip.FileInfoHeader(fi)
		if err != nil {
			return nil
		}
		hdr.Name = rel
		hdr.Method = zip.Deflate // sıkıştırma
		// hdr.Modified = fi.ModTime() // (Go 1.17+ için)

		wtr, err := zw.CreateHeader(hdr)
		if err != nil {
			log.Println("zip hdr:", err)
			return nil
		}
		if _, err := io.Copy(wtr, f); err != nil {
			log.Println("zip copy:", err)
			return nil
		}
		return nil
	})
}

// srcDir'i zipPath'e ziple
func zipDirectory(srcDir, zipPath string) error {
	zf, err := os.Create(zipPath)
	if err != nil {
		return err
	}
	defer zf.Close()

	zw := zip.NewWriter(zf)
	defer zw.Close()

	return filepath.Walk(srcDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(srcDir, path)
		if err != nil {
			return err
		}
		rel = filepath.ToSlash(rel)
		if rel == "." { // kök dizinin kendisi
			return nil
		}
		if info.IsDir() {
			_, err := zw.Create(rel + "/")
			return err
		}
		fh, err := zip.FileInfoHeader(info)
		if err != nil {
			return err
		}
		fh.Name = rel
		fh.Method = zip.Deflate
		w, err := zw.CreateHeader(fh)
		if err != nil {
			return err
		}
		f, err := os.Open(path)
		if err != nil {
			return err
		}
		defer f.Close()
		_, err = io.Copy(w, f)
		return err
	})
}

func mkdirHandler(w http.ResponseWriter, r *http.Request) {
	p := r.URL.Query().Get("abs")
	name := r.URL.Query().Get("name")
	if p == "" || name == "" {
		http.Error(w, "Eksik parametre", http.StatusBadRequest)
		return
	}
	if err := os.MkdirAll(filepath.Join(p, name), os.ModePerm); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	_, _ = w.Write([]byte("OK"))
}

func deleteHandler(w http.ResponseWriter, r *http.Request) {
	p := r.URL.Query().Get("abs")
	if p == "" {
		http.Error(w, "Eksik parametre", http.StatusBadRequest)
		return
	}
	if !safeToDelete(p) {
		http.Error(w, "Güvenlik nedeniyle bu yol silinemez", http.StatusForbidden)
		return
	}
	if err := safeRemoveAll(p); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	_, _ = w.Write([]byte("OK"))
}

// ── İSİM ve YOL KONTROLLERİ ────────────────────────────────────

func isValidName(name string) bool {
	if name == "" {
		return false
	}
	if strings.ContainsAny(name, `\/:*?"<>|`) {
		return false
	}
	return true
}

// sunucu klasörünü/EXE'yi tehlikeye atacak hamleleri engelle
func safeToMutate(src, dst string) bool {
	exe, _ := os.Executable()
	exeDir := filepath.Clean(filepath.Dir(exe))
	if src != "" {
		s := filepath.Clean(src)
		if isDriveRoot(s) || isInsideOrSame(s, exeDir) {
			return false
		}
	}
	if dst != "" {
		d := filepath.Clean(dst)
		// drive köküne yazma yok, sunucu klasörüne yazma yok
		if isDriveRoot(d) || isInsideOrSame(d, exeDir) {
			return false
		}
	}
	return true
}

// ── DOSYA/KLASÖR KOPYALAMA ─────────────────────────────────────

func copyFile(src, dst string, overwrite bool) error {
	if !overwrite {
		if _, err := os.Stat(dst); err == nil {
			return fmt.Errorf("target exists: %s", dst)
		}
	}
	if err := os.MkdirAll(filepath.Dir(dst), os.ModePerm); err != nil {
		return err
	}

	sf, err := os.Open(src)
	if err != nil {
		return err
	}
	defer sf.Close()

	info, err := sf.Stat()
	if err != nil {
		return err
	}

	df, err := os.OpenFile(dst, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, info.Mode())
	if err != nil {
		return err
	}
	defer df.Close()

	if _, err := io.Copy(df, sf); err != nil {
		return err
	}
	// Best-effort zaman damgaları
	at, mt := info.ModTime(), info.ModTime()
	_ = os.Chtimes(dst, at, mt)
	return nil
}

func copyDir(src, dst string, overwrite bool) error {
	// src bir dizin olmalı
	sInfo, err := os.Stat(src)
	if err != nil {
		return err
	}
	if !sInfo.IsDir() {
		return fmt.Errorf("source is not a directory")
	}

	// Hedef mevcut ve overwrite=false ise hata
	if !overwrite {
		if _, err := os.Stat(dst); err == nil {
			return fmt.Errorf("target exists: %s", dst)
		}
	}
	if err := os.MkdirAll(dst, os.ModePerm); err != nil {
		return err
	}

	return filepath.WalkDir(src, func(p string, d fs.DirEntry, wErr error) error {
		if wErr != nil {
			return wErr
		}
		rel, _ := filepath.Rel(src, p)
		target := filepath.Join(dst, rel)

		if d.IsDir() {
			return os.MkdirAll(target, os.ModePerm)
		}
		// dosya
		return copyFile(p, target, overwrite)
	})
}

func moveAny(src, dst string, overwrite bool) error {
	if !overwrite {
		if _, err := os.Stat(dst); err == nil {
			return fmt.Errorf("target exists: %s", dst)
		}
	}
	if err := os.MkdirAll(filepath.Dir(dst), os.ModePerm); err != nil {
		return err
	}

	// Önce rename dene
	if err := os.Rename(src, dst); err == nil {
		return nil
	} else {
		// EXDEV veya başka sebep: kopyala, sonra sil
		sInfo, sErr := os.Stat(src)
		if sErr != nil {
			return sErr
		}

		if sInfo.IsDir() {
			if err := copyDir(src, dst, overwrite); err != nil {
				return err
			}
			return os.RemoveAll(src)
		} else {
			if err := copyFile(src, dst, overwrite); err != nil {
				return err
			}
			return os.Remove(src)
		}
	}
}

func updateHandler(w http.ResponseWriter, r *http.Request) {
	old, err := os.Executable()
	if err != nil {
		log.Printf("update: executable path error: %v", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	exeDir := filepath.Dir(old)
	tmp := filepath.Join(exeDir, "server_update_temp.exe")
	out, err := os.Create(tmp)
	if err != nil {
		log.Printf("update: create temp failed: %v", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	defer out.Close()

	if _, err := io.Copy(out, r.Body); err != nil {
		log.Printf("update: write temp failed: %v", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	_, _ = w.Write([]byte("OK"))

	go func() {
		time.Sleep(1 * time.Second)
		if runtime.GOOS == "windows" {
			cmdExe := filepath.Join(os.Getenv("SystemRoot"), "System32", "cmd.exe")
			if _, err := os.Stat(cmdExe); err != nil {
				cmdExe = "cmd.exe"
			}
			relTmp := filepath.Base(tmp)
			relOld := filepath.Base(old)
			script := fmt.Sprintf("ping 127.0.0.1 -n 2 > NUL && move /Y \"%s\" \"%s\" && start \"\" \"%s\"", relTmp, relOld, relOld)
			cmd := exec.Command(cmdExe, "/C", script)
			cmd.Dir = exeDir
			cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
			if err := cmd.Start(); err != nil {
				log.Printf("update: cmd swap failed: %v", err)
				return
			}
		} else {
			helper := filepath.Join(exeDir, "update_helper.exe")
			if err := exec.Command(helper, old, tmp).Start(); err != nil {
				log.Printf("update: helper start failed: %v", err)
				return
			}
		}
		os.Exit(0)
	}()
}

// file/dir kopyalama (rename fallback'ı için)

// /api/rename?key=...&abs=C:\path\old.txt&newname=new.txt
func renameHandler(w http.ResponseWriter, r *http.Request) {
	abs := r.URL.Query().Get("abs")
	newName := r.URL.Query().Get("newname")
	if abs == "" || newName == "" {
		http.Error(w, "Eksik parametre", http.StatusBadRequest)
		return
	}
	if isDriveRoot(abs) {
		http.Error(w, "Kök sürücü yeniden adlandırılamaz", http.StatusBadRequest)
		return
	}
	dst := filepath.Join(filepath.Dir(abs), newName)
	if err := os.Rename(abs, dst); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	_, _ = w.Write([]byte("OK"))
}

// /api/move?key=...&src=C:\a\Klasor&dst=C:\x\y\&overwrite=1
// dst klasör ise içine taşır; dst dosya gibi bitiyorsa dosya adına taşır.
func moveHandler(w http.ResponseWriter, r *http.Request) {
	src := r.URL.Query().Get("src")
	dst := r.URL.Query().Get("dst")
	overwrite := r.URL.Query().Get("overwrite") == "1"
	if src == "" || dst == "" {
		http.Error(w, "Eksik parametre", http.StatusBadRequest)
		return
	}
	if isDriveRoot(src) {
		http.Error(w, "Kök sürücü taşınamaz", http.StatusBadRequest)
		return
	}
	// dst bir klasörse içine taşımak için gerçek hedefi belirle
	dInfo, derr := os.Stat(dst)
	if derr == nil && dInfo.IsDir() {
		dst = filepath.Join(dst, filepath.Base(src))
	}
	if err := moveAny(src, dst, overwrite); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	_, _ = w.Write([]byte("OK"))
}

// /api/copy?key=...&src=C:\a\Klasor&dst=C:\x\y\&ensure=1&overwrite=1
// ensure=1 ise dst klasörünü yoksa oluşturur.
func copyHandler(w http.ResponseWriter, r *http.Request) {
	src := r.URL.Query().Get("src")
	dst := r.URL.Query().Get("dst")
	ensure := r.URL.Query().Get("ensure") == "1"
	overwrite := r.URL.Query().Get("overwrite") == "1"

	if src == "" || dst == "" {
		http.Error(w, "Eksik parametre", http.StatusBadRequest)
		return
	}
	sInfo, err := os.Stat(src)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	if ensure {
		if err := os.MkdirAll(dst, os.ModePerm); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
	}

	// Eğer dst klasörse içine kopyala
	if dInfo, err := os.Stat(dst); err == nil && dInfo.IsDir() {
		if sInfo.IsDir() {
			dst = filepath.Join(dst, filepath.Base(src))
			if err := copyDir(src, dst, overwrite); err != nil {
				http.Error(w, err.Error(), http.StatusInternalServerError)
				return
			}
		} else {
			dst = filepath.Join(dst, filepath.Base(src))
			if err := copyFile(src, dst, overwrite); err != nil {
				http.Error(w, err.Error(), http.StatusInternalServerError)
				return
			}
		}
	} else {
		// dst bir dosya adı olabilir
		if sInfo.IsDir() {
			if err := copyDir(src, dst, overwrite); err != nil {
				http.Error(w, err.Error(), http.StatusInternalServerError)
				return
			}
		} else {
			if err := copyFile(src, dst, overwrite); err != nil {
				http.Error(w, err.Error(), http.StatusInternalServerError)
				return
			}
		}
	}
	_, _ = w.Write([]byte("OK"))
}

// ---- helpers ----

func safeRename(src, dst string) error {
	// önce parent oluştur
	if err := os.MkdirAll(filepath.Dir(dst), os.ModePerm); err != nil {
		return err
	}
	if err := os.Rename(src, dst); err != nil {
		// farklı diske taşıma (EXDEV) ise: kopyala + sil
		var linkErr *os.LinkError
		if errors.As(err, &linkErr) && errors.Is(linkErr.Err, syscall.EXDEV) {
			if err := copyAny(src, dst, true); err != nil {
				return err
			}
			return os.RemoveAll(src)
		}
		return err
	}
	return nil
}

func copyAny(src, dst string, overwrite bool) error {
	info, err := os.Stat(src)
	if err != nil {
		return err
	}
	if info.IsDir() {
		return copyDir(src, dst, overwrite)
	}
	return copyFile(src, dst, overwrite)
}

// /api/rename?key=...&abs=C:\path\old.txt&newname=Yeni.txt
// /api/rename?key=...&abs=C:\path\old.txt&newname=Yeni.txt
// /api/rename?abs=C:\path\oldName.txt&newname=YeniAd.txt

func featuresHandler(w http.ResponseWriter, r *http.Request) {
	jsonOut(w, map[string]bool{
		"rename": true,
		"move":   true,
		"copy":   true,
	})
}

// /api/move?key=...&src=C:\a\b.txt&dst=C:\x\y\  (dst klasörse b.txt oraya taşınır)
// /api/move?key=...&src=C:\a\Klasor&dst=C:\x\y\KlasorYeni

func maybeUpdateUnicastFromSender(savedPath string) {
	base := filepath.Base(savedPath)
	if !strings.HasPrefix(base, "sender_") || !strings.HasSuffix(base, ".txt") {
		return
	}
	ip := strings.TrimSuffix(strings.TrimPrefix(base, "sender_"), ".txt")

	// Basit doğrulama (IPv4 bekliyoruz)
	if p := net.ParseIP(ip); p == nil || p.To4() == nil {
		log.Println("sender_ dosyasında geçersiz IP:", ip)
		return
	}

	// Listeyi tamamen bu IP ile değiştir
	cfg.Announce.TargetUnicast = []string{ip}
	if err := saveConfig(cfg); err != nil {
		log.Println("Config kaydı hatası:", err)
		return
	}
	log.Println("🟢 Hızlı Tara: TargetUnicast güncellendi →", ip)
}

// ───────────────────────────── TCP ──────────────────────────────

// Header format (JSON line, optional for backward-compat):
// {"type":"file","dest":"C:\\path\\to\\file.txt"}
// {"type":"zipdir","dest":"C:\\path\\to\\destFolder","name":"FolderName"}
type tcpHeader struct {
	Type string `json:"type"` // "file" or "zipdir"
	Dest string `json:"dest"` // absolute path
	Name string `json:"name"` // optional, for zipdir
}

func startTCP() {
	ln, err := net.Listen("tcp", fmt.Sprintf(":%d", cfg.TCPPort))
	if err != nil {
		log.Println("TCP listen error:", err)
		return
	}
	tcpListener = ln
	go func() {
		log.Println("TCP listening on", cfg.TCPPort)
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			go handleTCP(conn)
		}
	}()
}

func stopTCP() {
	if tcpListener != nil {
		_ = tcpListener.Close()
	}
}

func handleTCP(conn net.Conn) {
	defer conn.Close()
	rd := bufio.NewReader(conn)
	line, err := rd.ReadString('\n')
	if err != nil {
		return
	}
	line = strings.TrimSpace(line)

	// Backward-compatible: plain path
	if !strings.HasPrefix(line, "{") {
		dest := line
		if dest == "" {
			return
		}
		if err := os.MkdirAll(filepath.Dir(dest), os.ModePerm); err != nil {
			log.Println("mkdir:", err)
			return
		}
		f, err := os.Create(dest)
		if err != nil {
			log.Println("create:", err)
			return
		}
		if _, err := io.Copy(f, rd); err != nil {
			log.Println("copy:", err)
			_ = f.Close()
			return
		}
		_ = f.Close()
		log.Println("Saved (file):", dest)

		// 🔽 EKLENDİ: sender_*.txt geldiyse config'i güncelle
		maybeUpdateUnicastFromSender(dest) // sender_*.txt geldiyse TargetUnicast'ı günceller ve kaydeder
		applyConfigChanged()               // announce’ı yeniden başlat + tray tooltip’i tazele
		return
	}

	// JSON header path
	var hdr tcpHeader
	if err := json.Unmarshal([]byte(line), &hdr); err != nil {
		log.Println("header json:", err)
		return
	}
	switch strings.ToLower(hdr.Type) {
	case "file":
		if hdr.Dest == "" {
			return
		}
		if err := os.MkdirAll(filepath.Dir(hdr.Dest), os.ModePerm); err != nil {
			log.Println("mkdir:", err)
			return
		}
		f, err := os.Create(hdr.Dest)
		if err != nil {
			log.Println("create:", err)
			return
		}
		if _, err := io.Copy(f, rd); err != nil {
			log.Println("copy:", err)
			_ = f.Close()
			return
		}
		_ = f.Close()
		log.Println("Saved (file):", hdr.Dest)

		// 🔽 EKLENDİ
		maybeUpdateUnicastFromSender(hdr.Dest)
		applyConfigChanged()

	case "zipdir":
		if hdr.Dest == "" {
			return
		}
		// Write stream to temp .zip
		tmpZip := filepath.Join(os.TempDir(), fmt.Sprintf("dirrecv_%d.zip", time.Now().UnixNano()))
		tf, err := os.Create(tmpZip)
		if err != nil {
			log.Println("tmp create:", err)
			return
		}
		if _, err := io.Copy(tf, rd); err != nil {
			tf.Close()
			log.Println("tmp copy:", err)
			return
		}
		_ = tf.Close()

		// Extract into hdr.Dest (create base folder if provided name)
		target := hdr.Dest
		if hdr.Name != "" {
			target = filepath.Join(target, hdr.Name)
		}
		if err := unzipTo(tmpZip, target); err != nil {
			log.Println("unzip:", err)
			_ = os.Remove(tmpZip)
			return
		}
		_ = os.Remove(tmpZip)
		log.Println("Saved (folder):", target)

		// ✅ ZIP başarıyla açıldıktan sonra İSTEMCİYE ACK gönder
		_, _ = conn.Write([]byte("OK\n"))

	}
}

func applyConfigChanged() {
	// announce döngüsünü yeni cfg ile hemen kullan
	stopAnnounce()
	startAnnounce()

	// systray tooltip’i güncelle (varsa)
	systray.SetTooltip(fmt.Sprintf("%s (TCP %d, HTTP %d)", cfg.Name, cfg.TCPPort, cfg.HTTPPort))
}

// unzipTo extracts zip archive at zipPath into destDir (securely)
func unzipTo(zipPath, destDir string) error {
	if err := os.MkdirAll(destDir, os.ModePerm); err != nil {
		return err
	}
	r, err := zip.OpenReader(zipPath)
	if err != nil {
		return err
	}
	defer r.Close()

	for _, f := range r.File {
		// Clean path & prevent traversal
		clean := filepath.Clean(f.Name)
		p := filepath.Join(destDir, clean)
		if !strings.HasPrefix(p, filepath.Clean(destDir)+string(os.PathSeparator)) {
			// path traversal attempt
			continue
		}
		if f.FileInfo().IsDir() {
			if err := os.MkdirAll(p, os.ModePerm); err != nil {
				return err
			}
			continue
		}
		// ensure dir exists
		if err := os.MkdirAll(filepath.Dir(p), os.ModePerm); err != nil {
			return err
		}
		rc, err := f.Open()
		if err != nil {
			return err
		}
		dst, err := os.Create(p)
		if err != nil {
			rc.Close()
			return err
		}
		if _, err := io.Copy(dst, rc); err != nil {
			dst.Close()
			rc.Close()
			return err
		}
		dst.Close()
		rc.Close()
		// best-effort timestamps (optional)
		ts := f.Modified
		_ = os.Chtimes(p, ts, ts)
	}
	return nil
}

// ─────────────────────────── ANNOUNCE ───────────────────────────

func startAnnounce() {
	stopAnnounce() // single loop
	announceStopCh = make(chan struct{})
	go announceLoop(announceStopCh)
}

func stopAnnounce() {
	if announceStopCh != nil {
		close(announceStopCh)
		announceStopCh = nil
	}
}

func announceLoop(stopCh chan struct{}) {
	payload := func() []byte {
		msg := map[string]interface{}{
			"name":     cfg.Name,
			"ip":       getOutboundIP(),
			"tcpPort":  cfg.TCPPort,
			"httpPort": cfg.HTTPPort,
			"when":     time.Now().Format(time.RFC3339),
		}
		b, _ := json.Marshal(msg)
		return b
	}
	interval := time.Duration(cfg.Announce.IntervalSecond) * time.Second

	for {
		select {
		case <-stopCh:
			return
		default:
			b := payload()

			// Multicast
			if cfg.Announce.McastGroup != "" && cfg.Announce.McastPort != 0 {
				addr := fmt.Sprintf("%s:%d", cfg.Announce.McastGroup, cfg.Announce.McastPort)
				if u, err := net.ResolveUDPAddr("udp4", addr); err == nil {
					if c, err := net.DialUDP("udp4", nil, u); err == nil {
						_, _ = c.Write(b)
						c.Close()
					}
				}
			}
			// Directed broadcast to subnets
			for _, s := range cfg.Announce.TargetSubnets {
				for _, dst := range expandSubnetToBroadcast(s, cfg.Announce.McastPort) {
					if u, err := net.ResolveUDPAddr("udp4", dst); err == nil {
						if c, err := net.DialUDP("udp4", nil, u); err == nil {
							_, _ = c.Write(b)
							c.Close()
						}
					}
				}
			}
			// Unicast targets
			for _, ip := range cfg.Announce.TargetUnicast {
				dst := fmt.Sprintf("%s:%d", ip, cfg.Announce.McastPort)
				if u, err := net.ResolveUDPAddr("udp4", dst); err == nil {
					if c, err := net.DialUDP("udp4", nil, u); err == nil {
						_, _ = c.Write(b)
						c.Close()
					}
				}
			}

			select {
			case <-stopCh:
				return
			case <-time.After(interval):
			}
		}
	}
}

// "192.168.7", "192.168.7.0/24" or "192.168.7.255"
func expandSubnetToBroadcast(s string, port int) []string {
	if strings.Contains(s, "/") {
		if _, ipnet, err := net.ParseCIDR(s); err == nil {
			bc := broadcastAddr(ipnet)
			return []string{fmt.Sprintf("%s:%d", bc.String(), port)}
		}
	}
	parts := strings.Split(s, ".")
	if len(parts) == 4 {
		return []string{fmt.Sprintf("%s:%d", s, port)}
	}
	if len(parts) == 3 {
		return []string{fmt.Sprintf("%s.255:%d", s, port)}
	}
	return nil
}

func broadcastAddr(n *net.IPNet) net.IP {
	ip := n.IP.To4()
	if ip == nil {
		return n.IP
	}
	mask := n.Mask
	return net.IPv4(
		ip[0]|^mask[0],
		ip[1]|^mask[1],
		ip[2]|^mask[2],
		ip[3]|^mask[3],
	)
}

func getOutboundIP() string {
	conn, err := net.Dial("udp", "8.8.8.8:80")
	if err != nil {
		return "127.0.0.1"
	}
	defer conn.Close()
	return conn.LocalAddr().(*net.UDPAddr).IP.String()
}
