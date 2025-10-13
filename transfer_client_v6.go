package main

import (
	"archive/zip"
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// progress message to GUI (UDP localhost:progressPort)
type progressMsg struct {
	Sent  int64 `json:"sent"`
	Total int64 `json:"total"`
}

// header for server (first line, JSON + \n)
type tcpHeader struct {
	Type string `json:"type"` // "file" or "zipdir"
	Dest string `json:"dest"` // absolute target dir (for file: parent; server will combine with basename)
	Name string `json:"name"` // for zipdir: base folder name
}

func main() {
	// usage: exe ip tcpPort fileOrDirPath progressPort [remoteDir]
	if len(os.Args) < 5 {
		return
	}
	serverIP := os.Args[1]
	tcpPort := os.Args[2]
	srcPath := os.Args[3]
	progressPort := os.Args[4]
	remoteDir := ""
	if len(os.Args) >= 6 {
		remoteDir = os.Args[5]
	}

	info, err := os.Stat(srcPath)
	if err != nil {
		return
	}

	// UDP progress
	udpAddr, _ := net.ResolveUDPAddr("udp4", net.JoinHostPort("127.0.0.1", progressPort))
	udpConn, _ := net.DialUDP("udp4", nil, udpAddr)
	defer func() {
		if udpConn != nil {
			udpConn.Close()
		}
	}()

	// compute total (sum of file sizes). For dir: raw sum, not compressed size.
	var total int64 = 0
	if info.IsDir() {
		filepath.Walk(srcPath, func(p string, fi os.FileInfo, e error) error {
			if e != nil {
				return nil
			}
			if !fi.IsDir() {
				total += fi.Size()
			}
			return nil
		})
	} else {
		total = info.Size()
	}

	// TCP connect
	conn, err := net.Dial("tcp", net.JoinHostPort(serverIP, tcpPort))
	if err != nil {
		return
	}
	defer conn.Close()
	bw := bufio.NewWriter(conn)

	var sent int64 = 0
	lastReport := time.Now()

	report := func(force bool) {
		if udpConn == nil {
			return
		}
		// throttle: every 300ms or if forced
		if !force && time.Since(lastReport) < 300*time.Millisecond {
			return
		}
		lastReport = time.Now()
		b, _ := json.Marshal(progressMsg{Sent: sent, Total: total})
		udpConn.Write(b)
	}

	// copy with progress counting
	copyWithProgress := func(dst io.Writer, src io.Reader) error {
		buf := make([]byte, 256*1024)
		for {
			n, er := src.Read(buf)
			if n > 0 {
				w, ew := dst.Write(buf[:n])
				if ew != nil {
					return ew
				}
				sent += int64(w)
				report(false)
			}
			if er == io.EOF {
				break
			}
			if er != nil {
				return er
			}
		}
		return nil
	}

	if info.IsDir() {
		// send header for folder
		h := tcpHeader{
			Type: "zipdir",
			Dest: strings.TrimRight(remoteDir, `\/`),
			Name: filepath.Base(srcPath),
		}
		hb, _ := json.Marshal(h)
		fmt.Fprintf(bw, "%s\n", string(hb))
		bw.Flush()

		// stream ZIP directly into TCP
		zw := zip.NewWriter(bw)
		base := filepath.Clean(srcPath)

		filepath.Walk(srcPath, func(p string, fi os.FileInfo, e error) error {
			if e != nil {
				return nil
			}
			rel, _ := filepath.Rel(base, p)
			rel = filepath.ToSlash(rel) // zip needs forward slashes
			if fi.IsDir() {
				// directories are implicit in zip via file paths; skip explicit dir entries
				return nil
			}
			// ensure entry path is under base
			if strings.HasPrefix(rel, "..") {
				return nil
			}
			w, err := zw.Create(rel)
			if err != nil {
				return nil
			}
			f, err := os.Open(p)
			if err != nil {
				return nil
			}
			_ = copyWithProgress(w, f)
			f.Close()
			return nil
		})
		zw.Close()
		bw.Flush()
		report(true)
	} else {
		// send header for single file
		destFile := filepath.Join(strings.TrimRight(remoteDir, `\/`), filepath.Base(srcPath))
		h := tcpHeader{Type: "file", Dest: destFile}
		hb, _ := json.Marshal(h)
		fmt.Fprintf(bw, "%s\n", string(hb))
		bw.Flush()

		f, err := os.Open(srcPath)
		if err != nil {
			return
		}
		_ = copyWithProgress(bw, f)
		f.Close()
		bw.Flush()
		report(true)
	}

	// final "complete" report
	if udpConn != nil {
		b, _ := json.Marshal(progressMsg{Sent: total, Total: total})
		udpConn.Write(b)
	}
}
