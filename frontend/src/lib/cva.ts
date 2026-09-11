type CompoundVariant<V extends Record<string, Record<string, string>>> = Partial<{ [K in keyof V]: keyof V[K] }> & {
  class: string | ((props: { [K in keyof V]: keyof V[K] }) => string)
}

export type CvaOptions<V extends Record<string, Record<string, string>>, D extends Partial<{ [K in keyof V]: keyof V[K] }> = {}> = {
  variants?: V
  default?: D
  compoundVariants?: CompoundVariant<V>[]
}

/**
 * Creates a class-variant function that maps variant props to CSS classes.
 *
 * @template V A record describing all variant groups and their possible values
 * @template D A record describing default variant values for the variant groups in V
 *
 * @param {string} base Base CSS class applied to every output
 * @param {{ variants?: V; default?: D }} options options with variants and default values
 * - `variants`: A mapping of variant names to allowed variant values and CSS classes.
 * - `default`: The default variant values applied if the user does not specify them. Class can use functions with variants to produce dyncamic classes
 * - `compoundVariants`: Specific class on some variants.
 * @example
 *  compoundVariants: [
 *    {
 *      variant: 'ghost',
 *      class: ({ color }) => `text-${color} hover:bg-${color}/10 active:bg-${color}/20`,
 *    },
 *  ],
 *
 * @returns {(props?: { [K in keyof V]?: keyof V[K] } & { className?: string }) => string} Returns a function that accepts variant props and returns a final class string.
 *
 * @example
 * const textVariants = cva("font-semibold", {
 *   variants: {
 *     size: { sm: "text-sm", lg: "text-lg" },
 *     variant: { default: "text-primary" },
 *     color: { primary: "text-blue-500", danger: "text-yellow-700" }
 *   },
 *   default: {
 *     size: "sm"
 *   }
 * })
 *
 * textVariants({ size: "lg", variant: "default" color: "primary" }) // => "font-semibold text-lg text-blue-500"
 */
export default function cva<V extends Record<string, Record<string, string>>, D extends Partial<{ [K in keyof V]: keyof V[K] }>>(
  base: string,
  options: CvaOptions<V, D>,
): (props?: { [K in keyof V]?: keyof V[K] } & { className?: string }) => string {
  return function func(
    props: {
      [K in keyof V]?: keyof V[K]
    } & { className?: string } = {},
  ) {
    let classes = [base]
    const finalProps = { ...options.default, ...Object.fromEntries(Object.entries(props).filter(([, v]) => v !== undefined)) }

    for (const variantName in options.variants) {
      const variantValue = finalProps[variantName]
      const variantMap = options.variants[variantName]

      if (variantValue && variantMap[variantValue]) {
        classes.push(variantMap[variantValue])
      }
    }

    if (options.compoundVariants) {
      for (const compound of options.compoundVariants) {
        let matches = true

        for (const key in compound) {
          if (key === 'class') continue
          if (finalProps[key] !== compound[key]) {
            matches = false
            break
          }
        }

        if (matches) {
          const c = compound.class
          classes.push(typeof c === 'function' ? c(finalProps as any) : c)
        }
      }
    }

    if (props.className) classes.push(props.className)

    return classes.filter(Boolean).join(' ')
  }
}

export type VariantProps<T extends (...args: any) => any> = T extends (props: infer P) => any ? P : never
