import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { EMPTY_VALUES, isInProgramFiles, requiredFields, toInput, validate, type FormValues } from './form'

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

describe('account size (reference_balance)', () => {
  const filled: FormValues = {
    ...EMPTY_VALUES,
    name: 'FN P1',
    firm: 'FundedNext',
    program: 'Stellar',
    phase: 'phase_1',
    login: '1234567',
    server: 'FundedNext-Server',
    starting_balance: '10000,00',
  }

  it('is optional on create and defaults to the starting balance', () => {
    expect(validate(filled).reference_balance).toBeUndefined()
    expect(toInput(filled).reference_balance).toBe('10000.00')
  })

  it('keeps an explicit account size on create', () => {
    expect(toInput({ ...filled, reference_balance: '25000' }).reference_balance).toBe('25000')
  })

  it('is required on edit and cannot be cleared', () => {
    expect(requiredFields(true).has('reference_balance')).toBe(true)
    expect(requiredFields(false).has('reference_balance')).toBe(false)
    expect(validate({ ...filled, reference_balance: ' ' }, true).reference_balance).toBe(
      uk.accounts.validation.accountSizeRequired,
    )
    expect(validate({ ...filled, reference_balance: '10000' }, true).reference_balance).toBeUndefined()
  })

  it('rejects a non-positive account size', () => {
    expect(validate({ ...filled, reference_balance: '0' }, true).reference_balance).toBe(
      uk.accounts.validation.positive,
    )
  })
})
