(define-module (cadr-fonts packages fonts)
  #:use-module (gnu packages python)
  #:use-module (gnu packages python-xyz)
  #:use-module (gnu packages xorg)
  #:use-module (guix build-system gnu)
  #:use-module (guix gexp)
  #:use-module (guix git-download)
  #:use-module (guix packages)
  #:use-module ((guix licenses)
                #:prefix license:)
  #:use-module (ice-9 ftw)
  #:use-module (srfi srfi-1)
  #:use-module (srfi srfi-13))

;; This is deliberately a local/manual recipe.  Resolve the checkout from this
;; module so that `-L /path/to/cadr-fonts/packaging/guix` works from any cwd.
(define %repository-root
  (canonicalize-path (string-append (dirname (current-filename))
                                    "/../../../..")))

(define (repository-relative-name file)
  (let ((prefix (string-append %repository-root "/")))
    (cond
      ((string=? file %repository-root)
       "")
      ((string-prefix? prefix file)
       (string-drop file
                    (string-length prefix)))
      (else #f))))

(define (selected-build-source? file stat)
  "Select only the local generator and its configuration."
  (let* ((relative (repository-relative-name file))
         (components (and relative
                          (string-split relative #\/))))
    (and relative
         (not (member ".git" components))
         (not (member "__pycache__" components))
         (not (string-suffix? ".pyc" relative))
         (or (string-null? relative)
             (string=? relative "LICENSE")
             (string=? relative "LICENSE.source")
             (string=? relative "config")
             (string-prefix? "config/" relative)
             (string=? relative "scripts")
             (string-prefix? "scripts/" relative)))))

(define %cadr-fonts-source
  (local-file %repository-root
              "cadr-fonts-local-source"
              #:recursive? #t
              #:select? selected-build-source?))

(define %cadr-source-checkout
  (string-append %repository-root "/sources/mit-cadr-system-software"))

(define %tracked-cadr-source?
  (git-predicate %cadr-source-checkout))

(define (selected-cadr-source? file stat)
  "Select the closed font witness from the pinned CADR source checkout."
  (let* ((prefix (string-append %cadr-source-checkout "/"))
         (relative
          (cond
           ((string=? file %cadr-source-checkout) "")
           ((string-prefix? prefix file)
            (string-drop file (string-length prefix)))
           (else #f))))
    (and relative
         ;; Keep directories traversable, but admit regular files only when
         ;; Git records them at the pinned submodule revision.
         (or (eq? (stat:type stat) 'directory)
             (%tracked-cadr-source? file stat))
         (or (string-null? relative)
             (string=? relative "src")
             (string=? relative "src/LICENSE")
             (string=? relative "src/lmfont")
             (string-prefix? "src/lmfont/" relative)
             (string=? relative "src/lmdoc")
             (string=? relative "src/lmdoc/char.18")
             (string=? relative "src/lmio1")
             (string=? relative "src/lmio1/fntcnv.28")
             (string=? relative "src/lmio")
             (string=? relative "src/lmio/fread.21")))))

(define %cadr-source-snapshot
  ;; The generator needs src/LICENSE, src/lmfont, and the three pinned source
  ;; files that close the Unicode mapping's historical evidence hashes.
  ;; Restricting the snapshot to those tracked witnesses avoids putting the
  ;; unrelated CADR system tree in every package derivation.
  (local-file %cadr-source-checkout
              "mit-cadr-system-software-snapshot"
              #:recursive? #t
              #:select? selected-cadr-source?))

(define %local-version
  "0+git.local")

;; Commit time of the pinned mit-cadr-system-software revision
;; 8e978d7d1704096a63edd4386a3b8326a2e584af.  Keeping this fixed makes the OTB
;; timestamps and release archive metadata reproducible in local Guix builds.
(define %source-date-epoch
  "1550169306")

(define (cadr-fonts-package group source-count runtime-count synopsis
                            description)
  (package
    (name (string-append "cadr-fonts-" group))
    (version %local-version)
    (source
     %cadr-fonts-source)
    (build-system gnu-build-system)
    (arguments
     (list
      #:phases
      #~(modify-phases %standard-phases
          (delete 'bootstrap)
          (delete 'configure)
          (add-after 'unpack 'add-pinned-cadr-source
            (lambda _
              (mkdir-p "sources")
              (copy-recursively #$%cadr-source-snapshot
                                "sources/mit-cadr-system-software")))
          (replace 'build
            (lambda _
              (setenv "LC_ALL" "C")
              (setenv "PYTHONDONTWRITEBYTECODE" "1")
              (setenv "SOURCE_DATE_EPOCH"
                      #$%source-date-epoch)
              (invoke "python3"
                      "scripts/build.py"
                      "--output"
                      "dist"
                      "--source-repository"
                      "sources/mit-cadr-system-software"
                      "--allow-source-snapshot"
                      "--omit-json")
              (invoke "python3"
                      "scripts/build_release.py"
                      "--distribution"
                      "dist"
                      "--release-dir"
                      "release"
                      "--version"
                      #$%local-version
                      "--source-date-epoch"
                      #$%source-date-epoch)))
          (replace 'check
            (lambda* (#:key tests? #:allow-other-keys)
              (when tests?
                (invoke "python3" "scripts/check_release_dist.py"
                        "--release-dir" "release")
                (invoke "python3" "scripts/check_otb.py"
                        (string-append "release/CADR-fonts-latin-"
                                       #$%local-version ".tar.gz")
                        (string-append "release/CADR-fonts-symbols-"
                                       #$%local-version ".tar.gz")))))
          (replace 'install
            (lambda* (#:key outputs #:allow-other-keys)
              (let* ((out (assoc-ref outputs "out"))
                     (archive (string-append "release/CADR-fonts-"
                                             #$group "-"
                                             #$%local-version ".tar.gz"))
                     (payload (string-append "CADR-fonts-"
                                             #$group "-"
                                             #$%local-version))
                     (staging "guix-release-payload")
                     (font-root (string-append out "/share/fonts/cadr-fonts/"
                                               #$group))
                     (data-root (string-append out "/share/cadr-fonts/"
                                               #$group))
                     (doc-root (string-append out "/share/doc/cadr-fonts-"
                                              #$group)))
                (mkdir-p staging)
                (invoke "tar" "-xzf" archive "-C" staging)
                (copy-recursively (string-append staging "/" payload
                                                 "/fonts/unicode/source")
                                  (string-append font-root "/bdf/source"))
                (copy-recursively (string-append staging "/" payload
                                                 "/fonts/unicode/runtime")
                                  (string-append font-root "/bdf/runtime"))
                (copy-recursively (string-append staging "/" payload
                                                 "/fonts/otb/source")
                                  (string-append font-root "/otb/source"))
                (copy-recursively (string-append staging "/" payload
                                                 "/fonts/otb/runtime")
                                  (string-append font-root "/otb/runtime"))
                (mkdir-p data-root)
                (copy-file (string-append staging "/" payload
                                          "/RELEASE-MANIFEST.json")
                           (string-append data-root "/RELEASE-MANIFEST.json"))
                (copy-recursively (string-append staging "/" payload
                                                 "/metadata")
                                  (string-append data-root "/metadata"))
                (mkdir-p doc-root)
                (copy-file (string-append staging "/" payload
                                          "/README.release.md")
                           (string-append doc-root "/README.release.md"))
                (copy-file (string-append staging "/" payload
                                          "/LICENSE.project")
                           (string-append doc-root "/LICENSE.project"))
                (copy-file (string-append staging "/" payload
                                          "/LICENSE.source")
                           (string-append doc-root "/LICENSE.source"))

                ;; The install contract exposes Unicode fonts only.  The raw
                ;; CADR-code BDFs stay in the generic release archives as
                ;; provenance material and can never enter a Guix profile.
                (when (file-exists? (string-append font-root "/raw"))
                  (error "raw CADR-code fonts entered the Guix output"))
                (let ((source-bdfs (find-files (string-append font-root
                                                              "/bdf/source")
                                               "\\.bdf$"))
                      (runtime-bdfs (find-files (string-append font-root
                                                               "/bdf/runtime")
                                                "\\.bdf$"))
                      (source-otbs (find-files (string-append font-root
                                                              "/otb/source")
                                               "\\.otb$"))
                      (runtime-otbs (find-files (string-append font-root
                                                               "/otb/runtime")
                                                "\\.otb$")))
                  (unless (and (= (length source-bdfs)
                                  #$source-count)
                               (= (length runtime-bdfs)
                                  #$runtime-count)
                               (= (length source-otbs)
                                  #$source-count)
                               (= (length runtime-otbs)
                                  #$runtime-count))
                    (error "installed CADR font profile counts changed")))))))))
    (native-inputs (list fonttosfnt python python-fonttools))
    (synopsis synopsis)
    (description description)
    (home-page "https://github.com/htayj/CADR-fonts")
    ;; Both the repository-authored build/release work and the recovered MIT
    ;; CADR font payload use BSD-3-Clause.  Their distinct notices are
    ;; installed as LICENSE.project and LICENSE.source, respectively.
    (license license:bsd-3)))

(define-public cadr-fonts-latin
  (cadr-fonts-package "latin" 118 42
   "CADR bitmap fonts containing visible Basic Latin glyphs"
   "CADR Fonts recovers bitmap fonts from the MIT CADR source and System 46
runtime.  This package contains the complete source and runtime artifacts that
have at least one visible Basic Latin letter.  It installs ISO 10646-1 BDF
fonts and display-equivalent OTB wrappers while retaining the two historical
profiles as separate directories."))

(define-public cadr-fonts-symbols
  (cadr-fonts-package "symbols" 33 7
   "CADR specialty bitmap fonts without visible Basic Latin letters"
   "CADR Fonts recovers bitmap fonts from the MIT CADR source and System 46
runtime.  This package contains the complementary specialty set, including
drawing, symbol, APL, Cyrillic, Greek, mathematical, music, and sprite
families.  It installs ISO 10646-1 BDF fonts and display-equivalent OTB
wrappers while retaining the two historical profiles as separate
directories."))
