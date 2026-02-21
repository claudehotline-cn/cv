declare module 'markdown-it-texmath' {
    import MarkdownIt from 'markdown-it';

    interface TexMathOptions {
        engine?: any;
        delimiters?: 'dollars' | 'brackets' | 'gitlab' | 'julia' | 'kramdown';
        katexOptions?: Record<string, any>;
    }

    const texmath: (md: MarkdownIt, options?: TexMathOptions) => void;
    export default texmath;
}
