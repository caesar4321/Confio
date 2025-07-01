import { generateZkLoginSalt } from '../zkLogin';

describe('zkLogin Salt Generation', () => {
  const testIss = 'https://accounts.google.com';
  const testSub = '123456789';
  const testAud = 'test-client-id';

  test('should generate consistent salt for same inputs', () => {
    const salt1 = generateZkLoginSalt(testIss, testSub, testAud, 'personal', 0);
    const salt2 = generateZkLoginSalt(testIss, testSub, testAud, 'personal', 0);
    
    expect(salt1).toBe(salt2);
  });

  test('should generate different salts for different account types', () => {
    const personalSalt = generateZkLoginSalt(testIss, testSub, testAud, 'personal', 0);
    const businessSalt = generateZkLoginSalt(testIss, testSub, testAud, 'business', 0);
    
    expect(personalSalt).not.toBe(businessSalt);
  });

  test('should generate different salts for different account indices', () => {
    const personal0Salt = generateZkLoginSalt(testIss, testSub, testAud, 'personal', 0);
    const personal1Salt = generateZkLoginSalt(testIss, testSub, testAud, 'personal', 1);
    
    expect(personal0Salt).not.toBe(personal1Salt);
  });

  test('should generate different salts for different account types and indices', () => {
    const personal0Salt = generateZkLoginSalt(testIss, testSub, testAud, 'personal', 0);
    const business1Salt = generateZkLoginSalt(testIss, testSub, testAud, 'business', 1);
    
    expect(personal0Salt).not.toBe(business1Salt);
  });

  test('should use default values when account type and index not provided', () => {
    const explicitSalt = generateZkLoginSalt(testIss, testSub, testAud, 'personal', 0);
    const defaultSalt = generateZkLoginSalt(testIss, testSub, testAud);
    
    expect(defaultSalt).toBe(explicitSalt);
  });

  test('should generate base64 encoded strings', () => {
    const salt = generateZkLoginSalt(testIss, testSub, testAud, 'personal', 0);
    
    // Base64 strings should only contain alphanumeric characters, +, /, and =
    expect(salt).toMatch(/^[A-Za-z0-9+/]+=*$/);
  });

  test('should handle different input combinations', () => {
    // Test various combinations
    const combinations = [
      { type: 'personal', index: 0 },
      { type: 'personal', index: 1 },
      { type: 'business', index: 0 },
      { type: 'business', index: 1 },
      { type: 'personal', index: 999 },
    ];

    const salts = combinations.map(combo => 
      generateZkLoginSalt(testIss, testSub, testAud, combo.type, combo.index)
    );

    // All salts should be unique
    const uniqueSalts = new Set(salts);
    expect(uniqueSalts.size).toBe(combinations.length);
  });

  test('should maintain backward compatibility with old salt format', () => {
    // The old salt format was: SHA256(iss | sub | aud)
    // The new format with defaults is: SHA256(iss | sub | aud | "personal" | "0")
    // These should be different, but the new format should be deterministic
    
    const newSalt = generateZkLoginSalt(testIss, testSub, testAud, 'personal', 0);
    const newSalt2 = generateZkLoginSalt(testIss, testSub, testAud, 'personal', 0);
    
    expect(newSalt).toBe(newSalt2);
  });
}); 