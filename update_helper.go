// update_helper.go
package main

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

func main() {
	if len(os.Args) < 3 {
		fmt.Println("usage: update_helper <oldExePath> <newFilePath>")
		return
	}
	oldPath := os.Args[1]
	newPath := os.Args[2]

	// bekle: eski exe kapansın
	for i := 0; i < 30; i++ {
		if canWrite(oldPath) {
			break
		}
		time.Sleep(200 * time.Millisecond)
	}

	// önce taşımayı dene
	if err := replaceFile(newPath, oldPath); err != nil {
		fmt.Println("replace failed:", err)
		return
	}

	// yeni exe'yi başlat
	cmd := exec.Command(oldPath, "--config", "server_config.json")
	cmd.Dir = filepath.Dir(oldPath)
	_ = cmd.Start()
}

func canWrite(path string) bool {
	f, err := os.OpenFile(path, os.O_WRONLY, 0)
	if err == nil {
		_ = f.Close()
		return true
	}
	return false
}

func replaceFile(src, dst string) error {
	// sil ve yeniden adlandır
	_ = os.Remove(dst)
	if err := os.Rename(src, dst); err == nil {
		return nil
	}
	// rename olmadıysa kopyala
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	if _, err := io.Copy(out, in); err != nil {
		return err
	}
	_ = os.Remove(src)
	return nil
}
