/**
 * Form validation utilities
 * Provides validation for individual fields and parameter sets (all-or-none groups)
 */

export interface FieldValidation {
	field: string;
	message: string;
}

export interface ParameterSet {
	name: string;
	fields: string[];
	description?: string;
}

/**
 * Validates that required fields are present and non-empty
 */
export function validateRequired(
	data: Record<string, any>,
	requiredFields: string[]
): FieldValidation[] {
	const errors: FieldValidation[] = [];

	for (const field of requiredFields) {
		const value = data[field];
		if (value === undefined || value === null || value === '') {
			errors.push({
				field,
				message: 'This field is required'
			});
		}
	}

	return errors;
}

/**
 * Validates numeric ranges
 */
export function validateRange(
	data: Record<string, any>,
	field: string,
	min?: number,
	max?: number
): FieldValidation | null {
	const value = data[field];

	if (value === undefined || value === null || value === '') {
		return null; // Empty values handled by validateRequired
	}

	const num = Number(value);

	if (isNaN(num)) {
		return {
			field,
			message: 'Must be a valid number'
		};
	}

	if (min !== undefined && num < min) {
		return {
			field,
			message: `Must be at least ${min}`
		};
	}

	if (max !== undefined && num > max) {
		return {
			field,
			message: `Must be at most ${max}`
		};
	}

	return null;
}

/**
 * Validates parameter sets (all-or-none groups)
 * If any field in the set is provided, all required fields in the set must be provided
 */
export function validateParameterSets(
	data: Record<string, any>,
	parameterSets: ParameterSet[]
): FieldValidation[] {
	const errors: FieldValidation[] = [];

	for (const set of parameterSets) {
		const providedFields = set.fields.filter((field) => {
			const value = data[field];
			return value !== undefined && value !== null && value !== '';
		});

		// If some but not all fields are provided, that's an error
		if (providedFields.length > 0 && providedFields.length < set.fields.length) {
			const missingFields = set.fields.filter((field) => !providedFields.includes(field));

			for (const field of missingFields) {
				errors.push({
					field,
					message: `All fields in "${set.name}" must be provided together`
				});
			}
		}
	}

	return errors;
}

/**
 * Validates string patterns (e.g., IP addresses, hostnames)
 */
export function validatePattern(
	data: Record<string, any>,
	field: string,
	pattern: RegExp,
	message: string
): FieldValidation | null {
	const value = data[field];

	if (value === undefined || value === null || value === '') {
		return null; // Empty values handled by validateRequired
	}

	if (!pattern.test(String(value))) {
		return {
			field,
			message
		};
	}

	return null;
}

/**
 * Common patterns for validation
 */
export const patterns = {
	ipv4: /^(\d{1,3}\.){3}\d{1,3}$/,
	hostname: /^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$/,
	fqdn: /^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/,
	// Network name (flexible pattern for Hyper-V virtual switches)
	networkName: /^[\w\s\-\.]+$/
};

/**
 * Validates IPv4 address
 */
export function validateIPv4(value: string): boolean {
	if (!patterns.ipv4.test(value)) {
		return false;
	}

	const octets = value.split('.').map(Number);
	return octets.every((octet) => octet >= 0 && octet <= 255);
}

/**
 * Validates CIDR prefix (0-32 for IPv4)
 */
export function validateCIDRPrefix(value: number): boolean {
	return value >= 0 && value <= 32;
}

/**
 * Combines multiple validation results into a single error map
 */
export function combineValidationErrors(
	validations: (FieldValidation | FieldValidation[] | null)[]
): Record<string, string> {
	const errorMap: Record<string, string> = {};

	for (const validation of validations) {
		if (!validation) continue;

		const errors = Array.isArray(validation) ? validation : [validation];

		for (const error of errors) {
			// Only keep the first error for each field
			if (!errorMap[error.field]) {
				errorMap[error.field] = error.message;
			}
		}
	}

	return errorMap;
}

/**
 * Checks if there are any validation errors
 */
export function hasErrors(errors: Record<string, string>): boolean {
	return Object.keys(errors).length > 0;
}

/**
 * Clears validation errors for specific fields
 */
export function clearFieldErrors(
	errors: Record<string, string>,
	fields: string[]
): Record<string, string> {
	const newErrors = { ...errors };
	for (const field of fields) {
		delete newErrors[field];
	}
	return newErrors;
}
