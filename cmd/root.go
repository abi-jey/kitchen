package cmd

import (
    "os"

    "github.com/spf13/cobra"
)

// rootCmd represents the base command when called without any subcommands
var rootCmd = &cobra.Command{

    Use:   "kitchen",
    Short: "A brief description of your application",
    Long: `A longer description that spans multiple lines.
Use kitchen <command> <args>`,
    // Run: func(cmd *cobra.Command, args []string) {
    //     fmt.Println("kitchen called")
    // },
}

// Execute adds all child commands to the root command and sets flags appropriately.
// This is called by main.main(). It only   
// needs to be called once to initialize the
// root command and all its subcommands.
func Execute() {
    err := rootCmd.Execute()
    if err != nil {
        os.Exit(1)
    }
}