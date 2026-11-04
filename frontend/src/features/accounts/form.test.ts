import { describe, expect, it } from 'vitest'
import { isInProgramFiles } from './form'

describe('isInProgramFiles', () => {
  it.each([
    'C:\\Program Files\\MT5\\terminal64.exe',
    'C:\\Program Files (x86)\\MT5\\terminal64.exe',
    'C:\\PROGRAM FILES (X86)\\MT5\\TERMINAL64.EXE',
    'c:\\program files\\mt5\\terminal64.exe',
    'C:/Program Files/MT5/terminal64.exe',
    'C:\\Program Files/MT5\\terminal64.exe',
    'C:\\\\Program Files\\\\MT5//terminal64.exe',
    '"C:\\Program Files\\MT5\\terminal64.exe"',
    '  "C:\\Program Files\\MT5\\terminal64.exe"  ',
    'C:\\Program Files',
    'C:\\Program Files\\',
    'C:\\Program Files (x86)',
    'C:\\PROGRA~1\\MT5\\terminal64.exe',
    'C:\\progra~2\\MT5\\terminal64.exe',
    'C:/Progra~1/terminal64.exe',
    '%ProgramFiles%\\MT5\\terminal64.exe',
    '%PROGRAMFILES%\\MT5\\terminal64.exe',
    '%programfiles(x86)%\\MT5\\terminal64.exe',
    '%ProgramFiles(Arm)%\\MT5\\terminal64.exe',
    '%ProgramW6432%/MT5/terminal64.exe',
    '"%ProgramFiles%\\MT5\\terminal64.exe"',
  ])('forbids %s', (path) => {
    expect(isInProgramFiles(path)).toBe(true)
  })

  it.each([
    'C:\\MT5\\terminal64.exe',
    'D:\\MT5\\fn-p1\\terminal64.exe',
    'C:\\Program Files Backup\\MT5\\terminal64.exe',
    'C:\\Program Files (x86) Old\\MT5\\terminal64.exe',
    'C:\\ProgramFiles\\MT5\\terminal64.exe',
    'C:\\MT5\\Program Files\\terminal64.exe',
    'C:\\Users\\Borys\\Program Files\\MT5\\terminal64.exe',
    'D:\\Program Files\\MT5\\terminal64.exe',
    'C:\\PROGRA~3\\MT5\\terminal64.exe',
    'C:\\PROGRA~10\\MT5\\terminal64.exe',
    '%MT5_HOME%\\fn-p1\\terminal64.exe',
    '%UNKNOWN%\\terminal64.exe',
    '%ProgramFilesX%\\terminal64.exe',
    '',
  ])('allows lookalike %s', (path) => {
    expect(isInProgramFiles(path)).toBe(false)
  })
})
