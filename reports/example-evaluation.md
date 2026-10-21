# Code review evaluation

Static heuristics and a small public synthetic benchmark are not a security certification or evidence of real-world model performance.

- Macro F1 score: 0.639
- Micro Precision: 0.733
- Micro Recall: 0.611
- Micro F1: 0.667
- Task Coverage: 0.958

| Task | Status | F1 | Correct | False positives | Missed |
| --- | --- | --- | --- | --- | --- |
| mutable-list-buffer | evaluated | 1.000 | mutable-default:1 | — | — |
| mutable-dict-constructor | evaluated | 1.000 | mutable-default:1 | — | — |
| mutable-set-default | evaluated | 0.000 | — | — | mutable-default:1 |
| bare-except-number | evaluated | 1.000 | bare-except:4 | — | — |
| bare-except-cache | evaluated | 1.000 | bare-except:4 | — | — |
| bare-except-retry | evaluated | 0.000 | — | bare-except:4 | bare-except:5 |
| shell-module-run | evaluated | 1.000 | shell-true:4 | — | — |
| shell-import-alias | evaluated | 0.000 | — | — | shell-true:4 |
| shell-popen-alias | evaluated | 1.000 | shell-true:4 | — | — |
| dynamic-eval-formula | evaluated | 1.000 | dynamic-exec:2 | — | — |
| dynamic-exec-settings | evaluated | 1.000 | dynamic-exec:3 | — | — |
| dynamic-exec-compiled | evaluated | 0.000 | — | — | dynamic-exec:3 |
| multi-buffer-and-handler | evaluated | 0.667 | mutable-default:1 | — | bare-except:4 |
| multi-all-rules-same-line | evaluated | 0.667 | dynamic-exec:3, shell-true:7 | — | mutable-default:3, bare-except:8 |
| clean-none-buffer | evaluated | 1.000 | — | — | — |
| clean-string-default | evaluated | 0.000 | — | mutable-default:1 | — |
| clean-tuple-default | evaluated | 1.000 | — | — | — |
| clean-typed-handler | evaluated | 1.000 | — | — | — |
| clean-explicit-exception | evaluated | 0.000 | — | bare-except:4 | — |
| clean-shell-false-module | evaluated | 1.000 | — | — | — |
| clean-shell-false-alias | evaluated | 0.000 | — | shell-true:4 | — |
| clean-no-shell-keyword | evaluated | 1.000 | — | — | — |
| clean-issue-words-in-data | evaluated | 1.000 | — | — | — |
| clean-compile-only | missing | 0.000 | — | — | — |
