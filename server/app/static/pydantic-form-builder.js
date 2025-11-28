/**
 * Pydantic Form Builder
 * 
 * Builds forms directly from Pydantic model metadata (via OpenAPI/JSON Schema)
 * instead of using custom YAML schemas. This is Phase 7 of the schema migration.
 * 
 * Usage:
 *   const formBuilder = new PydanticFormBuilder();
 *   await formBuilder.init();
 *   const formHtml = formBuilder.buildForm('ManagedDeploymentRequest', values);
 */

class PydanticFormBuilder {
    constructor() {
        this.schemas = null;
        this.openApiSpec = null;
    }

    /**
     * Initialize the form builder by fetching OpenAPI spec from FastAPI
     */
    async init() {
        try {
            const response = await fetch('/openapi.json', { credentials: 'same-origin' });
            if (!response.ok) {
                throw new Error(`Failed to fetch OpenAPI spec: ${response.status}`);
            }
            this.openApiSpec = await response.json();
            this.schemas = this.openApiSpec.components?.schemas || {};
        } catch (error) {
            console.error('Failed to initialize Pydantic form builder:', error);
            throw error;
        }
    }

    /**
     * Get a schema definition by name
     */
    getSchema(schemaName) {
        return this.schemas[schemaName] || null;
    }

    /**
     * Extract field metadata from Pydantic JSON Schema
     */
    extractFieldMetadata(property, propertyName, schema) {
        const field = {
            id: propertyName,
            label: this.formatLabel(propertyName),
            type: this.mapJsonTypeToInputType(property),
            description: property.description || '',
            required: (schema.required || []).includes(propertyName),
            default: property.default,
            validations: {}
        };

        // Extract validation constraints
        if (property.minimum !== undefined) field.validations.minimum = property.minimum;
        if (property.maximum !== undefined) field.validations.maximum = property.maximum;
        if (property.minLength !== undefined) field.validations.minLength = property.minLength;
        if (property.maxLength !== undefined) field.validations.maxLength = property.maxLength;
        if (property.pattern !== undefined) field.validations.pattern = property.pattern;

        // Handle anyOf (nullable fields)
        if (property.anyOf) {
            const nonNullTypes = property.anyOf.filter(t => t.type !== 'null');
            if (nonNullTypes.length === 1) {
                field.type = this.mapJsonTypeToInputType(nonNullTypes[0]);
                if (nonNullTypes[0].minimum !== undefined) field.validations.minimum = nonNullTypes[0].minimum;
                if (nonNullTypes[0].maximum !== undefined) field.validations.maximum = nonNullTypes[0].maximum;
            }
        }

        return field;
    }

    /**
     * Map JSON Schema types to HTML input types
     */
    mapJsonTypeToInputType(property) {
        if (property.type === 'string') {
            // Check for secret/password fields by name
            if (property.title && (property.title.toLowerCase().includes('password') || property.title.toLowerCase().includes('pw'))) {
                return 'secret';
            }
            return 'string';
        }
        if (property.type === 'integer') return 'integer';
        if (property.type === 'number') return 'number';
        if (property.type === 'boolean') return 'boolean';
        
        // Handle anyOf (nullable types)
        if (property.anyOf) {
            const nonNullTypes = property.anyOf.filter(t => t.type !== 'null');
            if (nonNullTypes.length === 1) {
                return this.mapJsonTypeToInputType(nonNullTypes[0]);
            }
        }
        
        return 'string'; // fallback
    }

    /**
     * Format a field name into a human-readable label
     */
    formatLabel(fieldName) {
        // Convert snake_case to Title Case
        return fieldName
            .split('_')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ')
            .replace(/\bGb\b/g, 'GB')
            .replace(/\bCpu\b/g, 'CPU')
            .replace(/\bVm\b/g, 'VM')
            .replace(/\bId\b/g, 'ID')
            .replace(/\bIp\b/g, 'IP')
            .replace(/\bDns\b/g, 'DNS')
            .replace(/\bV4\b/g, 'IPv4')
            .replace(/\bLa\b/g, 'Local Admin')
            .replace(/\bUid\b/g, 'Username')
            .replace(/\bPw\b/g, 'Password');
    }

    /**
     * Flatten nested model into flat field list for form display
     */
    flattenModel(schemaName, prefix = '') {
        const schema = this.getSchema(schemaName);
        if (!schema || !schema.properties) {
            return [];
        }

        const fields = [];
        for (const [propName, propDef] of Object.entries(schema.properties)) {
            const fieldId = prefix ? `${prefix}.${propName}` : propName;
            
            // Check if this is a nested model reference
            if (propDef.$ref) {
                const refSchemaName = propDef.$ref.split('/').pop();
                // Recursively flatten nested models
                fields.push(...this.flattenModel(refSchemaName, fieldId));
            } else {
                // Regular field
                const field = this.extractFieldMetadata(propDef, propName, schema);
                field.id = fieldId;
                field.group = prefix || 'general';
                fields.push(field);
            }
        }
        
        return fields;
    }

    /**
     * Build HTML for a single form field
     */
    buildField(field, currentValue = null) {
        const fieldId = `field-${field.id.replace(/\./g, '-')}`;
        const requiredPill = field.required ? '<span class="field-required-pill">Required</span>' : '';
        const labelText = this.escapeHtml(field.label);
        const description = field.description ? `<p class="field-description">${this.escapeHtml(field.description)}</p>` : '';
        const inputControl = this.buildInputControl(field, fieldId, currentValue);

        return `
            <div class="schema-field" data-field-id="${this.escapeHtml(field.id)}">
                <div class="field-header">
                    <div class="field-title">
                        <label for="${fieldId}" class="field-label">${labelText}</label>
                        ${requiredPill}
                    </div>
                </div>
                <div class="field-control">${inputControl}</div>
                ${description}
            </div>
        `;
    }

    /**
     * Build HTML input control for a field
     */
    buildInputControl(field, fieldId, currentValue = null) {
        const type = field.type || 'string';
        const value = currentValue !== null && currentValue !== undefined ? currentValue : (field.default ?? '');
        const requiredAttr = field.required ? 'required' : '';
        const placeholder = field.hint ? `placeholder="${this.escapeHtml(field.hint)}"` : '';
        const name = field.id;

        if (type === 'boolean') {
            const checked = value === true ? 'checked' : '';
            return `
                <label class="checkbox-field">
                    <input type="checkbox" id="${fieldId}" name="${name}" ${checked} />
                    <span>Enable</span>
                </label>
            `;
        }

        if (type === 'integer' || type === 'number') {
            const min = field.validations.minimum !== undefined ? `min="${field.validations.minimum}"` : '';
            const max = field.validations.maximum !== undefined ? `max="${field.validations.maximum}"` : '';
            const step = type === 'integer' ? '1' : 'any';
            const valueAttr = value !== '' ? `value="${this.escapeHtml(value)}"` : '';
            return `<input type="number" inputmode="numeric" step="${step}" id="${fieldId}" name="${name}" ${min} ${max} ${placeholder} ${valueAttr} ${requiredAttr} />`;
        }

        if (type === 'multiline') {
            return `<textarea id="${fieldId}" name="${name}" rows="4" ${placeholder} ${requiredAttr}>${this.escapeHtml(value)}</textarea>`;
        }

        const inputType = type === 'secret' ? 'password' : 'text';
        const patternValue = field.validations.pattern ? this.escapeHtml(field.validations.pattern) : '';
        const pattern = patternValue ? `pattern="${patternValue}"` : '';
        const valueAttr = value !== '' ? `value="${this.escapeHtml(value)}"` : '';
        return `<input type="${inputType}" id="${fieldId}" name="${name}" ${pattern} ${placeholder} ${valueAttr} ${requiredAttr} />`;
    }

    /**
     * Escape HTML to prevent XSS
     */
    escapeHtml(value) {
        if (value === null || value === undefined) {
            return '';
        }
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /**
     * Collect form values into an object matching the Pydantic model structure
     */
    collectFormValues(formElement, fields) {
        const values = {};
        
        fields.forEach(field => {
            const control = formElement.elements[field.id];
            if (!control) {
                return;
            }

            const type = field.type || 'string';
            if (type === 'boolean') {
                values[field.id] = control.checked;
            } else {
                const rawValue = control.value;
                if (rawValue === '') {
                    values[field.id] = null;
                } else if (type === 'integer') {
                    values[field.id] = parseInt(rawValue, 10);
                } else if (type === 'number') {
                    values[field.id] = parseFloat(rawValue);
                } else {
                    values[field.id] = rawValue;
                }
            }
        });

        return values;
    }

    /**
     * Restructure flat values into nested object structure matching Pydantic model
     */
    restructureValues(flatValues) {
        const nested = {};
        
        for (const [key, value] of Object.entries(flatValues)) {
            const parts = key.split('.');
            let current = nested;
            
            for (let i = 0; i < parts.length - 1; i++) {
                if (!current[parts[i]]) {
                    current[parts[i]] = {};
                }
                current = current[parts[i]];
            }
            
            current[parts[parts.length - 1]] = value;
        }
        
        return nested;
    }
}

// Export for use in other modules
window.PydanticFormBuilder = PydanticFormBuilder;
